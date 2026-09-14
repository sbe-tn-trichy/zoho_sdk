"""CSV and grouped Markdown count sheets."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from zoho.security import resolve_output_path
from zoho.sheet import ZohoSheetAPI
from .processor import (
    SKUMappingRow,
    StockCount,
    format_cell_address,
    parse_cell_address,
)


@dataclass(frozen=True)
class StockCountFiles:
    csv_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class StockCountSheetResult:
    workbook_id: str
    worksheet_name: str
    created_worksheet: bool
    rows_written: int


def _number(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_stock_count(count: StockCount) -> str:
    lines = ["# Neoseal stock count", "", f"Generated: {count.generated_at}",
             f"Scope: {'Location ' + count.location_id if count.location_id else 'Whole organization'}",
             f"Items: {len(count.rows)}", "",
             "Available quantity is Zoho's available_stock (location_available_stock for a location). "
             "Stock on hand is shown separately. Unknown balances require review; they are not zero. "
             "Quantities use each item's unit. Enter the physical count and remarks in the blank columns.", ""]
    previous = None
    for row in count.rows:
        section = (row.placement.group, row.placement.subgroup)
        if section != previous:
            lines.append("")
            if previous is None or previous[0] != section[0]:
                lines.extend([f"## {_md(section[0])}", ""])
            lines.extend([f"### {_md(section[1])}", "",
                          "| Order | SKU | Item | Unit | Status | Available | On hand | Physical count | Remarks |",
                          "|---:|---|---|---|---|---:|---:|---|---|"])
            previous = section
        cells = [str(row.sort_order), row.sku, row.name, row.unit, row.status,
                 _number(row.available_quantity) if row.available_quantity is not None else "Unknown",
                 _number(row.stock_on_hand) if row.stock_on_hand is not None else "Unknown", "",
                 "; ".join(row.warnings)]
        lines.append("| " + " | ".join(_md(c) for c in cells) + " |")
    if not count.rows:
        lines.append("No items found in the selected scope.")
    return "\n".join(lines) + "\n"


def write_stock_count(count: StockCount, output_dir: str = "output/neoseal_stock_count") -> StockCountFiles:
    """Write fixed filenames under output; explicit absolute directories are supported."""
    directory = Path(resolve_output_path(output_dir))
    directory.mkdir(parents=True, exist_ok=True)
    files = StockCountFiles(directory / "neoseal_stock_count.csv", directory / "neoseal_stock_count.md")
    fields = ["sort_order", "group", "subgroup", "item_id", "sku", "name", "unit", "status",
              "available_quantity", "stock_on_hand", "physical_count", "remarks", "source_group",
              "location_id", "generated_at"]
    with files.csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in count.rows:
            writer.writerow(dict(zip(fields, [row.sort_order, row.placement.group, row.placement.subgroup,
                row.item_id, row.sku, row.name, row.unit, row.status, _number(row.available_quantity),
                _number(row.stock_on_hand), "", "; ".join(row.warnings), row.source_group,
                count.location_id or "", count.generated_at])))
    files.markdown_path.write_text(render_stock_count(count), encoding="utf-8")
    return files


SHEET_FIELDS = (
    "count_label", "available_quantity", "unit", "physical_count", "remarks",
    "sku", "item_id", "stock_on_hand", "sort_order", "row_type",
)

FLAT_FIELDS = (
    "sort_order", "group", "subgroup", "item_id", "sku", "name", "unit",
    "available_quantity", "stock_on_hand", "physical_count", "remarks",
    "source_group", "location_id", "generated_at",
)


def _sheet_row(count: StockCount, row: Any, prior: Mapping[str, Any]) -> dict[str, str]:
    return {
        "count_label": row.name,
        "available_quantity": _number(row.available_quantity),
        "unit": row.unit,
        "physical_count": str(prior.get("physical_count") or ""),
        "remarks": str(prior.get("remarks") or ""),
        "sku": row.sku,
        "item_id": row.item_id,
        "stock_on_hand": _number(row.stock_on_hand),
        "sort_order": str(row.sort_order),
        "row_type": "item",
    }


def _display_rows(count: StockCount, prior_by_item: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, str]], list[tuple[int, str]]]:
    rows: list[dict[str, str]] = []
    headings: list[tuple[int, str]] = []
    previous_group = previous_subgroup = None
    for item in count.rows:
        group, subgroup = item.placement.group, item.placement.subgroup
        if group != previous_group:
            rows.append({"count_label": group, "row_type": "group"})
            headings.append((len(rows) + 1, "group"))
            previous_group, previous_subgroup = group, None
        if subgroup != previous_subgroup:
            rows.append({"count_label": subgroup, "row_type": "subgroup"})
            headings.append((len(rows) + 1, "subgroup"))
            previous_subgroup = subgroup
        rows.append(_sheet_row(count, item, prior_by_item.get(item.item_id, {})))
    return rows, headings


def write_flat_stock_count_to_sheet(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str,
    count: StockCount,
    count_worksheet_name: str = "Sheet1",
) -> StockCountSheetResult:
    """Write the complete one-row-per-item table to a separate worksheet."""
    workbook_id, worksheet_name = workbook_id.strip(), worksheet_name.strip()
    if not workbook_id or not worksheet_name or worksheet_name == count_worksheet_name:
        raise ValueError("Flat worksheet needs a workbook ID and a distinct worksheet name.")
    worksheets = sheet_client.list_sheets(workbook_id)
    created = worksheet_name not in worksheets
    if created:
        sheet_client.add_sheet(workbook_id, worksheet_name)
        prior_rows: list[Mapping[str, Any]] = []
    else:
        prior_rows = sheet_client.get_rows(workbook_id, worksheet_name, limit=1000)
    # A manual count may have been entered in either view. Prefer Flat's value.
    count_rows = sheet_client.get_rows(workbook_id, count_worksheet_name, limit=1000) if count_worksheet_name in worksheets else []
    prior_by_item = {
        str(row.get("item_id") or "").strip(): row
        for row in count_rows
        if isinstance(row, Mapping) and str(row.get("item_id") or "").strip()
    }
    prior_by_item.update({
        str(row.get("item_id") or "").strip(): row
        for row in prior_rows
        if isinstance(row, Mapping) and str(row.get("item_id") or "").strip()
    })
    rows = []
    for item in count.rows:
        prior = prior_by_item.get(item.item_id, {})
        rows.append({
            "sort_order": str(item.sort_order), "group": item.placement.group,
            "subgroup": item.placement.subgroup, "item_id": item.item_id,
            "sku": item.sku, "name": item.name, "unit": item.unit,
            "available_quantity": _number(item.available_quantity),
            "stock_on_hand": _number(item.stock_on_hand),
            "physical_count": str(prior.get("physical_count") or ""),
            "remarks": str(prior.get("remarks") or ""),
            "source_group": item.source_group, "location_id": count.location_id or "",
            "generated_at": count.generated_at,
        })
    if prior_rows:
        sheet_client.delete_rows(
            workbook_id, worksheet_name,
            [int(row["row_index"]) for row in prior_rows],
        )
    for column, field in enumerate(FLAT_FIELDS, start=1):
        sheet_client.set_cell(workbook_id, worksheet_name, 1, column, field)
    if rows:
        sheet_client.add_rows(workbook_id, worksheet_name, rows, header_row=1)
    return StockCountSheetResult(workbook_id, worksheet_name, created, len(rows))


def write_stock_count_to_sheet(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str,
    count: StockCount,
) -> StockCountSheetResult:
    """Replace one managed worksheet while retaining prior manual count fields.

    The worksheet is created if absent. Existing ``physical_count`` and
    ``remarks`` values are matched by item ID before the managed table is
    replaced; every other cell in this worksheet is owned by the workflow.
    """
    workbook_id = workbook_id.strip()
    worksheet_name = worksheet_name.strip()
    if not workbook_id or not worksheet_name:
        raise ValueError("workbook_id and worksheet_name are required.")
    worksheets = sheet_client.list_sheets(workbook_id)
    created = worksheet_name not in worksheets
    if created:
        sheet_client.add_sheet(workbook_id, worksheet_name)
        prior_rows: list[Mapping[str, Any]] = []
    else:
        prior_rows = sheet_client.get_rows(workbook_id, worksheet_name, limit=1000)
    prior_by_item = {
        str(row.get("item_id") or "").strip(): row
        for row in prior_rows
        if isinstance(row, Mapping) and str(row.get("item_id") or "").strip()
    }
    rows, headings = _display_rows(count, prior_by_item)
    if prior_rows:
        sheet_client.delete_rows(
            workbook_id, worksheet_name,
            [int(row["row_index"]) for row in prior_rows],
        )
    # Zoho Sheet may reject worksheet.content.set with API code 2867. Writing
    # header cells then appending records is supported by the same API version.
    for column, field in enumerate(SHEET_FIELDS, start=1):
        sheet_client.set_cell(workbook_id, worksheet_name, 1, column, field)
    if rows:
        sheet_client.add_rows(workbook_id, worksheet_name, rows, header_row=1)
        worksheet_id = sheet_client.get_sheet_id(workbook_id, worksheet_name)
        sheet_client.format_ranges(workbook_id, [
            {"worksheet_id": worksheet_id, "range": f"A{index}:A{index}",
             "font_size": "18" if kind == "group" else "14", "bold": "true"}
            for index, kind in headings
        ])
    return StockCountSheetResult(workbook_id, worksheet_name, created, len(count.rows))


MAPPING_FIELDS = ("sku", "cell", "item_id", "name", "stock_on_hand_cell")


def build_sku_cell_mappings(
    count: StockCount,
    qty_column: int = 2,
    soh_column: int = 8,
) -> list[SKUMappingRow]:
    """Build SKU to target cell mappings based on the ordered count worksheet layout."""
    rows, _ = _display_rows(count, {})
    mappings: list[SKUMappingRow] = []
    for index, row_dict in enumerate(rows, start=2):
        if row_dict.get("row_type") == "item":
            sku = str(row_dict.get("sku") or "").strip()
            item_id = str(row_dict.get("item_id") or "").strip()
            name = str(row_dict.get("count_label") or "").strip()
            qty_cell = format_cell_address(index, qty_column)
            soh_cell = format_cell_address(index, soh_column)
            mappings.append(SKUMappingRow(
                sku=sku,
                cell=qty_cell,
                item_id=item_id,
                name=name,
                stock_on_hand_cell=soh_cell,
            ))
    return mappings


def write_mapping_to_sheet(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str,
    count: StockCount,
    count_worksheet_name: str = "Sheet1",
) -> StockCountSheetResult:
    """Write or update the SKU-to-Cell mapping worksheet in the workbook."""
    workbook_id, worksheet_name = workbook_id.strip(), worksheet_name.strip()
    if not workbook_id or not worksheet_name or worksheet_name == count_worksheet_name:
        raise ValueError("Mapping worksheet needs a workbook ID and a distinct worksheet name.")
    worksheets = sheet_client.list_sheets(workbook_id)
    created = worksheet_name not in worksheets
    if created:
        sheet_client.add_sheet(workbook_id, worksheet_name)
        prior_rows: list[Mapping[str, Any]] = []
    else:
        prior_rows = sheet_client.get_rows(workbook_id, worksheet_name, limit=1000)

    prior_by_sku = {
        str(row.get("sku") or "").strip(): row
        for row in prior_rows
        if isinstance(row, Mapping) and str(row.get("sku") or "").strip()
    }

    generated_mappings = build_sku_cell_mappings(count)
    rows = []
    for m in generated_mappings:
        prior = prior_by_sku.get(m.sku, {})
        custom_cell = str(prior.get("cell") or "").strip()
        custom_soh = str(prior.get("stock_on_hand_cell") or "").strip()
        rows.append({
            "sku": m.sku,
            "cell": custom_cell or m.cell,
            "item_id": m.item_id,
            "name": m.name,
            "stock_on_hand_cell": custom_soh or (m.stock_on_hand_cell or ""),
        })

    if prior_rows:
        sheet_client.delete_rows(
            workbook_id, worksheet_name,
            [int(row["row_index"]) for row in prior_rows],
        )
    for column, field in enumerate(MAPPING_FIELDS, start=1):
        sheet_client.set_cell(workbook_id, worksheet_name, 1, column, field)
    if rows:
        sheet_client.add_rows(workbook_id, worksheet_name, rows, header_row=1)
    return StockCountSheetResult(workbook_id, worksheet_name, created, len(rows))


def fill_quantities_from_mapping(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    count_worksheet_name: str,
    count: StockCount,
    mapping_rows: Sequence[SKUMappingRow | Mapping[str, Any]] | None = None,
    mapping_worksheet_name: str = "Mapping",
    only_custom: bool = False,
) -> int:
    """Fill stock quantities into the count worksheet (Sheet1) using SKU-to-cell mappings."""
    workbook_id, count_worksheet_name = workbook_id.strip(), count_worksheet_name.strip()
    if not workbook_id or not count_worksheet_name:
        raise ValueError("workbook_id and count_worksheet_name are required.")

    if mapping_rows is None:
        raw_rows = sheet_client.get_rows(workbook_id, mapping_worksheet_name, limit=1000)
        mapping_rows = [r for r in raw_rows if isinstance(r, Mapping)]

    default_cells = {
        m.sku: (m.cell, m.stock_on_hand_cell)
        for m in build_sku_cell_mappings(count)
    } if only_custom else {}

    by_sku = {row.sku: row for row in count.rows}
    updated_count = 0
    for m in mapping_rows:
        if isinstance(m, SKUMappingRow):
            sku = m.sku
            cell_addr = m.cell
            soh_cell_addr = m.stock_on_hand_cell
        else:
            sku = str(m.get("sku") or "").strip()
            cell_addr = str(m.get("cell") or "").strip()
            soh_cell_addr = str(m.get("stock_on_hand_cell") or "").strip() or None

        if not sku or not cell_addr or sku not in by_sku:
            continue

        if only_custom and sku in default_cells:
            def_qty, def_soh = default_cells[sku]
            if cell_addr == def_qty and (not soh_cell_addr or soh_cell_addr == def_soh):
                continue

        item_row = by_sku[sku]
        row_idx, col_idx = parse_cell_address(cell_addr)
        qty_val = _number(item_row.available_quantity)
        sheet_client.set_cell(workbook_id, count_worksheet_name, row_idx, col_idx, qty_val)
        updated_count += 1

        if soh_cell_addr:
            try:
                soh_row, soh_col = parse_cell_address(soh_cell_addr)
                soh_val = _number(item_row.stock_on_hand)
                sheet_client.set_cell(workbook_id, count_worksheet_name, soh_row, soh_col, soh_val)
            except ValueError:
                pass

    return updated_count
