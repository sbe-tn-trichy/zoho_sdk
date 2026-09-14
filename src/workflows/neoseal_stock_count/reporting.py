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
    FlatStockSnapshot,
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


@dataclass(frozen=True)
class MissingFlatItem:
    item_id: str
    sku: str
    name: str
    row_index: int


@dataclass(frozen=True)
class FlatStockUpsertResult:
    workbook_id: str
    worksheet_name: str
    created_worksheet: bool
    rows_written: int
    missing_items: tuple[MissingFlatItem, ...]


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
    "item_id", "sku", "name", "unit",
    "available_quantity", "stock_on_hand", "physical_count", "remarks",
    "source_group", "location_id", "generated_at",
)
FLAT_UPSERT_FIELDS = (*FLAT_FIELDS, "packing")


def _read_flat_rows(sheet_client: ZohoSheetAPI, workbook_id: str, worksheet_name: str) -> list[Mapping[str, Any]]:
    """Read through blank row positions that terminate Zoho's tabular fetch."""
    tabular = sheet_client.get_rows(workbook_id, worksheet_name, limit=1000)
    response = sheet_client.request(
        "GET", workbook_id,
        params={"method": "worksheet.content.get", "worksheet_name": worksheet_name,
                "range": "A2:L1001"},
    )
    details = response.get("range_details", [])
    if not isinstance(details, list):
        raise ValueError("Flat worksheet returned invalid grid content.")
    grid = []
    for entry in details:
        row_index = int(entry["row_index"])
        if row_index > 1000:
            raise ValueError("Flat sheet has rows beyond the 1,000-row read limit.")
        cells = {int(cell["column_index"]): cell.get("content")
                 for cell in entry.get("row_details", [])}
        if str(cells.get(1) or "").strip():
            grid.append({"row_index": row_index, **{
                field: cells.get(index, "") for index, field in enumerate(FLAT_UPSERT_FIELDS, 1)
            }})
    if grid and len(grid) < len(tabular):
        raise ValueError("Flat grid read omitted rows present in the tabular fetch.")
    return grid if grid else tabular


def upsert_flat_stock_to_sheet(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str,
    snapshot: FlatStockSnapshot,
) -> FlatStockUpsertResult:
    """Update existing Flat items by ID and append new items without deleting rows."""
    workbook_id, worksheet_name = workbook_id.strip(), worksheet_name.strip()
    if not workbook_id or not worksheet_name:
        raise ValueError("Flat worksheet needs a workbook ID and worksheet name.")
    item_ids = [item.item_id for item in snapshot.rows]
    if any(not item_id.isdigit() for item_id in item_ids) or len(item_ids) != len(set(item_ids)):
        raise ValueError("Flat snapshot contains invalid or duplicate item IDs.")
    worksheets = sheet_client.list_sheets(workbook_id)
    created = worksheet_name not in worksheets
    if created:
        sheet_client.add_sheet(workbook_id, worksheet_name)
        prior_rows: list[Mapping[str, Any]] = []
        for column, field in enumerate(FLAT_UPSERT_FIELDS, start=1):
            sheet_client.set_cell(workbook_id, worksheet_name, 1, column, field)
    else:
        header_response = sheet_client.request(
            "GET", workbook_id,
            params={"method": "worksheet.content.get", "worksheet_name": worksheet_name,
                    "range": "A1:L1"},
        )
        header_details = header_response.get("range_details", [])
        if header_details:
            header_cells = {int(cell["column_index"]): str(cell.get("content") or "").strip()
                            for cell in header_details[0].get("row_details", [])}
            actual = tuple(header_cells.get(index, "") for index in range(1, len(FLAT_UPSERT_FIELDS) + 1))
            if actual != FLAT_UPSERT_FIELDS:
                raise ValueError("Flat worksheet headers do not match the expected column order.")
        prior_rows = _read_flat_rows(sheet_client, workbook_id, worksheet_name)
        if len(prior_rows) >= 1000:
            raise ValueError("Flat sheet has at least 1000 rows; cannot safely identify all existing items.")
        _validate_flat_rows(prior_rows)
        header = sheet_client.request(
            "GET", workbook_id,
            params={"method": "worksheet.content.get", "worksheet_name": worksheet_name,
                    "range": "L1"},
        )
        details = header.get("range_details", [])
        cells = details[0].get("row_details", []) if details else []
        value = str(cells[0].get("content") or "").strip() if cells else ""
        if value and value != "packing":
            raise ValueError("Flat column L is occupied; cannot add packing header.")
        if not value:
            sheet_client.set_cell(workbook_id, worksheet_name, 1, 12, "packing")
    known_ids = _validate_flat_rows(prior_rows)
    snapshot_ids = set(item_ids)
    missing_items = _missing_flat_items(prior_rows, snapshot_ids)
    snapshot_by_id = {item.item_id: item for item in snapshot.rows}
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for prior in prior_rows:
        item_id = str(prior.get("item_id") or "").strip()
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        if item_id in snapshot_by_id:
            item = snapshot_by_id[item_id]
            rows.append({
                "item_id": item.item_id,
                "sku": item.sku,
                "name": item.name,
                "unit": item.unit,
                "available_quantity": _number(item.available_quantity),
                "stock_on_hand": _number(item.stock_on_hand),
                "physical_count": str(prior.get("physical_count") or ""),
                "remarks": str(prior.get("remarks") or ""),
                "source_group": item.source_group,
                "location_id": snapshot.location_id or "",
                "generated_at": snapshot.generated_at,
                "packing": item.packing,
            })
        else:
            # Retain existing Flat items absent from current tracked Inventory fetch
            rows.append({
                field: str(prior.get(field) or "") for field in FLAT_UPSERT_FIELDS
            })

    for item in snapshot.rows:
        if item.item_id not in seen_ids:
            seen_ids.add(item.item_id)
            rows.append({
                "item_id": item.item_id,
                "sku": item.sku,
                "name": item.name,
                "unit": item.unit,
                "available_quantity": _number(item.available_quantity),
                "stock_on_hand": _number(item.stock_on_hand),
                "physical_count": "",
                "remarks": "",
                "source_group": item.source_group,
                "location_id": snapshot.location_id or "",
                "generated_at": snapshot.generated_at,
                "packing": item.packing,
            })

    if prior_rows:
        sheet_client.truncate_sheet(workbook_id, worksheet_name, criteria='"item_id" != \'\'')
    if rows:
        sheet_client.add_rows(workbook_id, worksheet_name, rows, header_row=1)

    return FlatStockUpsertResult(workbook_id, worksheet_name, created,
                                 len(snapshot.rows), missing_items)


def _validate_flat_rows(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("Flat sheet returned an invalid row.")
    known_ids = [str(row.get("item_id") or "").strip() for row in rows]
    if any(value and not value.isdigit() for value in known_ids):
        raise ValueError("Flat sheet contains a non-numeric item ID; check its headers and columns.")
    known_ids = [value for value in known_ids if value]
    if len(known_ids) != len(set(known_ids)):
        raise ValueError("Flat sheet contains duplicate item IDs.")
    return known_ids


def _missing_flat_items(
    rows: Sequence[Mapping[str, Any]], current_ids: set[str]
) -> tuple[MissingFlatItem, ...]:
    missing = []
    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        if item_id and item_id not in current_ids:
            row_index = row.get("row_index")
            if not isinstance(row_index, int) or row_index < 2:
                raise ValueError(f"Flat row for item {item_id} has no valid row_index.")
            missing.append(MissingFlatItem(item_id, str(row.get("sku") or ""),
                                           str(row.get("name") or ""), row_index))
    return tuple(missing)


def delete_approved_missing_flat_items(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str,
    snapshot: FlatStockSnapshot,
    approved_item_ids: Sequence[str],
) -> int:
    """Delete explicitly approved IDs only if still absent from the current snapshot."""
    approved = tuple(str(item_id).strip() for item_id in approved_item_ids)
    if not approved or any(not item_id.isdigit() for item_id in approved) or len(set(approved)) != len(approved):
        raise ValueError("Provide unique numeric approved item IDs.")
    workbook_id, worksheet_name = workbook_id.strip(), worksheet_name.strip()
    if not workbook_id or not worksheet_name:
        raise ValueError("Flat worksheet needs a workbook ID and worksheet name.")
    rows = _read_flat_rows(sheet_client, workbook_id, worksheet_name)
    if len(rows) >= 1000:
        raise ValueError("Flat sheet has at least 1000 rows; cannot safely identify all existing items.")
    _validate_flat_rows(rows)
    missing = {item.item_id: item for item in _missing_flat_items(
        rows, {item.item_id for item in snapshot.rows}
    )}
    unapproved = set(approved) - set(missing)
    if unapproved:
        raise ValueError("Approved IDs are no longer missing from the current Inventory snapshot: "
                         + ", ".join(sorted(unapproved)))
    # Delete from bottom to top, preserving indices as individual rows disappear.
    for row_index in sorted((missing[item_id].row_index for item_id in approved), reverse=True):
        sheet_client.delete_rows(workbook_id, worksheet_name, [row_index])
    return len(approved)


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
    count_worksheet_name: str = "StockCount",
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
            "item_id": item.item_id,
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
        formats = []
        item_start = None
        item_end = None
        for i, row in enumerate(rows, start=2):
            row_type = row.get("row_type")
            if row_type == "item":
                if item_start is None:
                    item_start = i
                item_end = i
            else:
                if item_start is not None:
                    formats.append({
                        "worksheet_id": worksheet_id,
                        "range": f"A{item_start}:J{item_end}",
                        "font_size": "10",
                        "bold": "false",
                    })
                    item_start = None
                    item_end = None
                formats.append({
                    "worksheet_id": worksheet_id,
                    "range": f"A{i}:A{i}",
                    "font_size": "16" if row_type == "group" else "14",
                    "bold": "true",
                })
        if item_start is not None:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"A{item_start}:J{item_end}",
                "font_size": "10",
                "bold": "false",
            })
        sheet_client.format_ranges(workbook_id, formats)
    return StockCountSheetResult(workbook_id, worksheet_name, created, len(count.rows))


CUSTOM_STOCK_COUNT_MAPPING: dict[str, str] = {
    # Left Table (Col C - QTY)
    # 105 PVC Solvent (Tin)
    "105-50-PVC-CLR-TIN": "C3",
    "105-100-PVC-CAN": "C4",
    "105-100-PVC-CLR-TIN": "C4",
    "105-250-PVC-CLR-TIN": "C5",
    "105-500-PVC-CLR-TIN": "C6",
    "105-1000-PVC-CLR-TIN": "C7",
    # 100/200 PVC Solvent (Tin / Can)
    "100-50-PVC-CLR-TIN": "C9",
    "200-50-UPVC-BLU-TIN": "C9",
    "100-100-PVC-CLR-TIN": "C10",
    "200-100-UPVC-BLU-TIN": "C10",
    "200-100-UPVC-CLR-TIN": "C10",
    "200-50-UPVC-BLU-CAN": "C11",
    "200-100-UPVC-BLU-CAN": "C12",
    "200-100-UPVC-CLR-CAN": "C12",
    # 205 UPVC Solvent (Tin / Can)
    "205-59-UPVC-BLU-TIN": "C14",
    "205-118-UPVC-BLU-TIN": "C15",
    "205-237-UPVC-BLU-TIN": "C16",
    "205-59-UPVC-BLU-CAN": "C17",
    "205-118-UPVC-BLU-CAN": "C18",
    "205-473-UPVC-BLU-TIN": "",
    "205-946-UPVC-BLU-TIN": "",
    # 300 CPVC Solvent (Tin)
    "300-50-CPVC-YEL-TIN": "C20",
    "300-100-CPVC-YEL-TIN": "C21",
    # 305 Heavy CPVC Solvent (Tin / Can)
    "305-59-CPVC-YEL-TIN": "C25",
    "305-118-CPVC-YEL-CAN": "C26",
    "305-118-CPVC-YEL-TIN": "C26",
    # Tubes
    "20-PVC-UPVC-CLR-TUBE": "C28",
    "305-25-CPVC-YEL-TUBE": "C29",
    # Silicon Sealant
    "701-260-B": "C31",
    "701-260-CLR": "C31",
    "701-260-W": "C31",
    "701-260-BLK": "C31",
    "701-260-WHT": "C31",
    "703-280": "C33",
    # Tape
    "6M-INSULATION-BLACK": "C35",
    "6M-INSULATION-BLUE": "C35",
    "6M-INSULATION-GREEN": "C35",
    "6M-INSULATION-RED": "C35",
    "6M-INSULATION-YELLOW": "C35",
    "5M-WHITE-12MM": "C37",
    "10M-YELLOW-12MM": "C38",
    "10M-WHITE-19MM": "C39",
    "10M-YELLOW-12MM-0.15": "C41",
    # Waterproofing
    "IWP-500-0.5": "C45",
    "IWP-500-1": "C46",
    "IWP-500-5": "C47",
    "501-1": "C52",
    "501-5": "C53",
    "566-1": "C55",
    "514-4": "C62",
    "514-10": "C63",
    "514-20": "C64",
    "508-2K-3": "C66",
    "508-2K-15": "C67",
    # Right Table (Col H - QTY)
    # PVC Ball Valve (GSP)
    "0.75-PVC-GSP": "H3",
    "1-PVC-GSP": "H4",
    "1.25-PVC-GSP": "H5",
    "1.5-PVC-GSP": "H6",
    "2-PVC-GSP": "H7",
    "2.5-PVC-GSP": "H8",
    "3-PVC-GSP": "H9",
    "0.5-PVC-GSP": "",
    # PVC Ball Valve (GSP Threaded)
    "0.75-PVC-GSP-TH": "H11",
    "1-PVC-GSP-TH": "H12",
    # UPVC Ball Valve (GS)
    "0.75-UPVC-GS": "H14",
    "1-UPVC-GS": "H15",
    "1.25-UPVC-GS": "H16",
    # UPVC Ball Valve (MS)
    "0.75-UPVC-MS": "H20",
    "1-UPVC-MS": "H21",
    # Cleaners
    "ND80-50": "H23",
    "ND80-100": "H24",
    "ND40-50": "",
    "ND40-100": "",
    # Thread Sealant
    "SARAL-HSR-25-BLUE": "H26",
    "SARAL-GP-100-RED": "H27",
    "SARAL-100-WHT": "H28",
    # Tile Grout
    "518-300": "H30",
    "518-1": "H31",
    # Tile Cleaner
    "503-500": "H34",
    "503-1000": "H35",
    "503-5000": "H36",
    # Epoxy Grout
    "802-20": "H38",
    "753-25": "H39",
    "DRAIN-50": "H40",
    # Waterproofing chemicals
    "516-10": "H57",
    "506-20": "H63",
    "507-10-L": "H67",
    "507-20-L": "H68",
    # Unlisted in count sheet
    "609-1": "",
    "Neoseal CN": "",
}

MAPPING_FIELDS = ("sku", "cell", "name", "item_id", "stock_on_hand_cell")


def build_sku_cell_mappings(
    count: StockCount,
    qty_column: int = 2,
    soh_column: int = 8,
    custom_mapping: Mapping[str, str] | None = None,
) -> list[SKUMappingRow]:
    """Build SKU to target cell mappings based on the count worksheet layout."""
    if custom_mapping is not None:
        mappings: list[SKUMappingRow] = []
        for row in count.rows:
            target_cell = custom_mapping.get(row.sku, "")
            mappings.append(SKUMappingRow(
                sku=row.sku,
                cell=target_cell,
                item_id=row.item_id,
                name=row.name,
                stock_on_hand_cell="",
            ))
        return mappings

    rows, _ = _display_rows(count, {})
    mappings = []
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
    count_worksheet_name: str = "StockCount",
    custom_mapping: Mapping[str, str] | None = None,
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

    generated_mappings = build_sku_cell_mappings(count, custom_mapping=custom_mapping)
    target_cells = {
        m.sku: str(prior_by_sku[m.sku].get("cell") or "").strip()
        if m.sku in prior_by_sku else m.cell
        for m in generated_mappings
    }
    parsed_cells = {sku: parse_cell_address(cell) for sku, cell in target_cells.items() if cell}
    grid: dict[tuple[int, int], str] = {}
    if parsed_cells:
        last_row = max(row for row, _ in parsed_cells.values())
        response = sheet_client.request(
            "GET", workbook_id,
            params={"method": "worksheet.content.get", "worksheet_name": count_worksheet_name,
                    "range": f"A1:I{last_row}"},
        )
        for row_entry in response.get("range_details", []):
            row_index = int(row_entry["row_index"])
            for cell_entry in row_entry.get("row_details", []):
                grid[(row_index, int(cell_entry["column_index"]))] = str(
                    cell_entry.get("content") or ""
                ).strip()
    rows = []
    for m in generated_mappings:
        if m.sku in prior_by_sku:
            prior = prior_by_sku[m.sku]
            target_cell = str(prior.get("cell") or "").strip()
            target_soh = str(prior.get("stock_on_hand_cell") or "").strip()
        else:
            target_cell = m.cell
            target_soh = m.stock_on_hand_cell or ""
        page_name = ""
        if target_cell:
            target_row, target_col = parsed_cells[m.sku]
            name_col = 1 if target_col <= 5 else 6
            page_name = grid.get((target_row, name_col), "")
            if not page_name:
                raise ValueError(f"StockCount product name is missing for {m.sku} at {target_cell}.")
        rows.append({
            "sku": m.sku,
            "cell": target_cell,
            "name": page_name,
            "item_id": m.item_id,
            "stock_on_hand_cell": target_soh,
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
    """Fill stock quantities into the count worksheet (StockCount) using SKU-to-cell mappings."""
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

    # Aggregate quantities by target cell address so multiple variants/colors
    # mapping to a single row sum together.
    qty_cells: dict[tuple[int, int], Decimal | None] = {}
    soh_cells: dict[tuple[int, int], Decimal | None] = {}
    cell_pairs: list[tuple[tuple[int, int], tuple[int, int] | None]] = []

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

        try:
            r_idx, c_idx = parse_cell_address(cell_addr)
        except ValueError:
            continue

        item_row = by_sku[sku]
        item_qty = item_row.available_quantity
        if (r_idx, c_idx) not in qty_cells:
            qty_cells[(r_idx, c_idx)] = item_qty
        elif item_qty is not None:
            existing = qty_cells[(r_idx, c_idx)]
            qty_cells[(r_idx, c_idx)] = (existing or Decimal(0)) + item_qty

        soh_pair: tuple[int, int] | None = None
        if soh_cell_addr:
            try:
                soh_r, soh_c = parse_cell_address(soh_cell_addr)
                soh_pair = (soh_r, soh_c)
                item_soh = item_row.stock_on_hand
                if (soh_r, soh_c) not in soh_cells:
                    soh_cells[(soh_r, soh_c)] = item_soh
                elif item_soh is not None:
                    existing_soh = soh_cells[(soh_r, soh_c)]
                    soh_cells[(soh_r, soh_c)] = (existing_soh or Decimal(0)) + item_soh
            except ValueError:
                pass

        if not any(p[0] == (r_idx, c_idx) for p in cell_pairs):
            cell_pairs.append(((r_idx, c_idx), soh_pair))

    updated_count = 0
    for (r_idx, c_idx), soh_pair in cell_pairs:
        qty_val = _number(qty_cells[(r_idx, c_idx)])
        sheet_client.set_cell(workbook_id, count_worksheet_name, r_idx, c_idx, qty_val)
        updated_count += 1
        if soh_pair:
            soh_r, soh_c = soh_pair
            soh_val = _number(soh_cells[(soh_r, soh_c)])
            sheet_client.set_cell(workbook_id, count_worksheet_name, soh_r, soh_c, soh_val)

    return updated_count


def zero_unmapped_stockcount_quantities(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    count_worksheet_name: str = "StockCount",
    mapping_worksheet_name: str = "Mapping",
) -> int:
    """Set QTY to zero for custom count lines that have no mapped SKU."""
    workbook_id = workbook_id.strip()
    if not workbook_id or not count_worksheet_name.strip() or not mapping_worksheet_name.strip():
        raise ValueError("Workbook, count worksheet, and mapping worksheet are required.")
    mapping_rows = sheet_client.get_rows(workbook_id, mapping_worksheet_name, limit=1000)
    mapped_cells = {
        str(row.get("cell") or "").strip().upper()
        for row in mapping_rows if isinstance(row, Mapping) and str(row.get("cell") or "").strip()
    }
    response = sheet_client.request(
        "GET", workbook_id,
        params={"method": "worksheet.content.get", "worksheet_name": count_worksheet_name,
                "range": "A1:I1000"},
    )
    grid = {
        (int(row["row_index"]), int(cell["column_index"])): str(cell.get("content") or "").strip()
        for row in response.get("range_details", [])
        for cell in row.get("row_details", [])
    }
    if any(grid.get((1, col)) != value for col, value in (
        (1, "PRODUCT"), (2, "PACK"), (3, "QTY"),
        (6, "PRODUCT"), (7, "PACK"), (8, "QTY"),
    )):
        raise ValueError("StockCount does not have the expected two-table product layout.")
    updated = 0
    for row in range(2, int(response.get("used_row") or 1) + 1):
        for product_col, pack_col, qty_col in ((1, 2, 3), (6, 7, 8)):
            if not grid.get((row, product_col)):
                continue
            # Category lines have no pack or quantity; item lines have at least one.
            if not (grid.get((row, pack_col)) or grid.get((row, qty_col))):
                continue
            cell = format_cell_address(row, qty_col)
            if cell in mapped_cells or grid.get((row, qty_col)) == "0":
                continue
            sheet_client.set_cell(workbook_id, count_worksheet_name, row, qty_col, "0")
            updated += 1
    return updated


def format_custom_stock_count_sheet(
    sheet_client: ZohoSheetAPI,
    *,
    workbook_id: str,
    worksheet_name: str = "StockCount",
) -> dict[str, Any]:
    """Format custom dual-column stock count sheet with proper cell merges and borders."""
    workbook_id = workbook_id.strip()
    worksheet_name = worksheet_name.strip()
    if not workbook_id or not worksheet_name:
        raise ValueError("workbook_id and worksheet_name are required.")

    worksheet_id = sheet_client.get_sheet_id(workbook_id, worksheet_name)

    res = sheet_client.request(
        "GET",
        workbook_id,
        params={
            "method": "worksheet.content.get",
            "worksheet_name": worksheet_name,
            "range": "A1:I100",
        },
    )

    used_row = int(res.get("used_row") or 72)
    grid: dict[tuple[int, int], str] = {}
    for r_entry in res.get("range_details", []):
        r_idx = int(r_entry["row_index"])
        for c_entry in r_entry.get("row_details", []):
            grid[(r_idx, int(c_entry["column_index"]))] = str(c_entry.get("content", "")).strip()

    formats: list[dict[str, Any]] = [
        {"worksheet_id": worksheet_id, "range": f"A1:A{used_row}", "horizontal_alignment": "start", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"B1:B{used_row}", "horizontal_alignment": "center", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"C1:C{used_row}", "horizontal_alignment": "end", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"D1:D{used_row}", "horizontal_alignment": "end", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"E1:E{used_row}", "border": {"border_type": "no_border"}},
        {"worksheet_id": worksheet_id, "range": f"F1:F{used_row}", "horizontal_alignment": "start", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"G1:G{used_row}", "horizontal_alignment": "center", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"H1:H{used_row}", "horizontal_alignment": "end", "vertical_alignment": "middle"},
        {"worksheet_id": worksheet_id, "range": f"I1:I{used_row}", "horizontal_alignment": "end", "vertical_alignment": "middle"},
        {
            "worksheet_id": worksheet_id,
            "range": "A1:D1",
            "bold": "true",
            "font_size": "11",
            "fill_color": "#e2e8f0",
            "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#94a3b8"},
        },
        {
            "worksheet_id": worksheet_id,
            "range": "F1:I1",
            "bold": "true",
            "font_size": "11",
            "fill_color": "#e2e8f0",
            "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#94a3b8"},
        },
    ]

    merged_count = 0
    for r in range(2, used_row + 1):
        lp = grid.get((r, 1), "")
        lpack = grid.get((r, 2), "")
        lqty = grid.get((r, 3), "")
        lavl = grid.get((r, 4), "")

        rp = grid.get((r, 6), "")
        rpack = grid.get((r, 7), "")
        rqty = grid.get((r, 8), "")
        ravl = grid.get((r, 9), "")

        # Left block
        if lp and not lpack and not lqty and not lavl:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"A{r}:D{r}",
                "merge_cell": "merge_range",
                "bold": "true",
                "font_size": "12",
                "fill_color": "#f1f5f9",
                "horizontal_alignment": "start",
                "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#94a3b8"},
            })
            merged_count += 1
        elif lp or lpack or lqty or lavl:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"A{r}:D{r}",
                "bold": "false",
                "font_size": "10",
                "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#cbd5e1"},
            })
        else:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"A{r}:D{r}",
                "border": {"border_type": "no_border"},
            })

        # Right block
        if rp and not rpack and not rqty and not ravl:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"F{r}:I{r}",
                "merge_cell": "merge_range",
                "bold": "true",
                "font_size": "12",
                "fill_color": "#f1f5f9",
                "horizontal_alignment": "start",
                "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#94a3b8"},
            })
            merged_count += 1
        elif rp or rpack or rqty or ravl:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"F{r}:I{r}",
                "bold": "false",
                "font_size": "10",
                "border": {"border_type": "all_border", "border_style": "solid", "border_color": "#cbd5e1"},
            })
        else:
            formats.append({
                "worksheet_id": worksheet_id,
                "range": f"F{r}:I{r}",
                "border": {"border_type": "no_border"},
            })

    sheet_client.format_ranges(workbook_id, formats)
    return {
        "workbook_id": workbook_id,
        "worksheet_name": worksheet_name,
        "rule_count": len(formats),
        "merged_headers_count": merged_count,
    }
