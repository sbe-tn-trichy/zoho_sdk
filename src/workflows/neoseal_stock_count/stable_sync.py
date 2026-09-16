"""Keep the custom count page linked to Flat through stable line IDs and SKUs."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from zoho.sheet import ZohoSheetAPI


@dataclass(frozen=True)
class CellChange:
    sheet: str
    row: int
    column: int
    content: str


@dataclass(frozen=True)
class StableSyncPlan:
    changes: tuple[CellChange, ...]
    formulas: Mapping[str, str]
    unplaced_skus: tuple[str, ...]
    stale_mapping_skus: tuple[str, ...]
    new_line_ids: int


def _grid(client: ZohoSheetAPI, workbook_id: str, sheet: str, last_column: str) -> dict[int, dict[int, str]]:
    metadata = client.request("GET", workbook_id, params={
        "method": "worksheet.content.get", "worksheet_name": sheet,
        "range": f"A1:{last_column}1",
    })
    last_row = max(1, int(metadata.get("used_row") or 1))
    response = client.request("GET", workbook_id, params={
        "method": "worksheet.content.get", "worksheet_name": sheet,
        "range": f"A1:{last_column}{last_row}",
    })
    return {
        int(row["row_index"]): {
            int(cell["column_index"]): str(cell.get("content") or "")
            for cell in row.get("row_details", [])
        }
        for row in response.get("range_details", [])
    }


def _text(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _line_id() -> str:
    return "SC-" + uuid.uuid4().hex


def build_stable_sync_plan(
    flat: Mapping[int, Mapping[int, str]],
    mapping: Mapping[int, Mapping[int, str]],
    count: Mapping[int, Mapping[int, str]],
) -> StableSyncPlan:
    """Plan changes without mutating the workbook; current displayed Pack is fallback."""
    if tuple(flat.get(1, {}).get(c, "") for c in (1, 2, 5, 12)) != (
        "item_id", "sku", "available_quantity", "packing"
    ):
        raise ValueError("Flat schema changed")
    if tuple(mapping.get(1, {}).get(c, "") for c in range(1, 6)) != (
        "sku", "cell", "name", "item_id", "stock_on_hand_cell"
    ):
        raise ValueError("Mapping schema changed")
    if tuple(count.get(1, {}).get(c, "") for c in (1, 2, 3, 6, 7, 8)) != (
        "PRODUCT", "PACK", "QTY", "PRODUCT", "PACK", "QTY"
    ):
        raise ValueError("StockCount layout changed")

    flat_by_sku: dict[str, tuple[str, str]] = {}
    flat_item_ids: set[str] = set()
    for row_num, row in flat.items():
        if row_num == 1 or not row.get(1):
            continue
        sku, item_id = row.get(2, "").strip(), row[1].strip()
        if not sku or sku in flat_by_sku or item_id in flat_item_ids:
            raise ValueError(f"Duplicate or missing Flat key at row {row_num}")
        flat_item_ids.add(item_id)
        flat_by_sku[sku] = (item_id, row.get(12, ""))

    line_locations: dict[str, tuple[int, int]] = {}
    locations: dict[str, tuple[int, int, int, int, str, str]] = {}
    changes: list[CellChange] = []
    new_line_ids = 0
    for row_num, row in count.items():
        if row_num == 1:
            continue
        for product_col, pack_col, qty_col, id_col, side in (
            (1, 2, 3, 10, "L"), (6, 7, 8, 11, "R")
        ):
            if not row.get(product_col) or not (row.get(pack_col) or row.get(qty_col) or row.get(id_col)):
                continue
            line_id = row.get(id_col, "").strip()
            if not line_id:
                line_id = _line_id()
                changes.append(CellChange("StockCount", row_num, id_col, line_id))
                new_line_ids += 1
            if line_id in line_locations:
                raise ValueError(f"Duplicate StockCount line ID {line_id}")
            line_locations[line_id] = (row_num, qty_col)
            locations[f"{side}{row_num}"] = (
                row_num, pack_col, qty_col, id_col, line_id, row[product_col]
            )
    mapped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    seen_skus: set[str] = set()
    stale_mapping: list[str] = []
    for row_num, row in mapping.items():
        if row_num == 1 or not row.get(1):
            continue
        sku, address = row[1].strip(), row.get(2, "").strip().upper()
        if sku in seen_skus:
            raise ValueError(f"Duplicate Mapping SKU {sku}")
        seen_skus.add(sku)
        if sku not in flat_by_sku:
            if address or row.get(6, "").strip():
                raise ValueError(f"Mapped SKU missing from Flat: {sku}")
            stale_mapping.append(sku)
            continue
        if row.get(4, "").strip() != flat_by_sku[sku][0]:
            raise ValueError(f"Mapping item ID differs from Flat for {sku}")
        stored_line_id = row.get(6, "").strip()
        if stored_line_id:
            if stored_line_id not in line_locations:
                raise ValueError(f"Mapping line ID has no StockCount row: {sku}")
            target_row, target_col = line_locations[stored_line_id]
            key = f"{'L' if target_col == 3 else 'R'}{target_row}"
        elif address:
            match = re.fullmatch(r"([CH])(\d+)", address)
            if not match:
                raise ValueError(f"Invalid Mapping address: {address}")
            key = f"{'L' if match[1] == 'C' else 'R'}{match[2]}"
            if key not in locations:
                raise ValueError(f"Mapping address has no StockCount product: {address}")
            stored_line_id = locations[key][4]
            changes.append(CellChange("Mapping", row_num, 6, stored_line_id))
        else:
            continue
        target_row, pack_col, qty_col, _, line_id, label = locations[key]
        if row.get(3, "") != label:
            raise ValueError(f"Mapping label mismatch for {sku}: {label!r}")
        correct_address = f"{'C' if qty_col == 3 else 'H'}{target_row}"
        if address != correct_address:
            changes.append(CellChange("Mapping", row_num, 2, correct_address))
        mapped[line_id].append((row_num, sku))

    if mapping.get(1, {}).get(6, "") != "line_id":
        if mapping.get(1, {}).get(6, ""):
            raise ValueError("Mapping F1 is occupied")
        changes.insert(0, CellChange("Mapping", 1, 6, "line_id"))
    for column, name in ((10, "left_line_id"), (11, "right_line_id")):
        if count.get(1, {}).get(column, "") != name:
            if count.get(1, {}).get(column, ""):
                raise ValueError(f"StockCount helper column {column} is occupied")
            changes.insert(0, CellChange("StockCount", 1, column, name))

    # The range expands at each sync; a buffer lets ordinary Flat appends recalculate
    # without editing the formulas on every refresh.
    last_flat_row = max(flat, default=1)
    limit = max(1000, last_flat_row + 1000)
    formulas: dict[str, str] = {}
    for row_num, pack_col, qty_col, _, line_id, _ in locations.values():
        members = sorted(mapped.get(line_id, []), key=lambda member: member[1])
        pack_addr = f"{'B' if pack_col == 2 else 'G'}{row_num}"
        qty_addr = f"{'C' if qty_col == 3 else 'H'}{row_num}"
        pack_fallback = _text(count[row_num].get(pack_col, ""))
        if members:
            terms = [
                f"SUMIF(Flat.B2:B{limit};{_text(sku)};Flat.E2:E{limit})"
                for _, sku in members
            ]
            formulas[qty_addr] = terms[0] if len(terms) == 1 else f"=SUM({';'.join(terms)})"
            if not formulas[qty_addr].startswith("="):
                formulas[qty_addr] = "=" + formulas[qty_addr]
            pack_values = {flat_by_sku[sku][1] for _, sku in members if flat_by_sku[sku][1]}
            if len(pack_values) > 1:
                raise ValueError(f"Conflicting Flat packing for {qty_addr}")
            if pack_values:
                pack_fallback = _text(next(iter(pack_values)))
            chosen_sku = next((sku for _, sku in members if flat_by_sku[sku][1]), members[0][1])
            lookup = f"VLOOKUP({_text(chosen_sku)};Flat.B2:L{limit};11;0)"
            formulas[pack_addr] = (
                f'=IFERROR(IF({lookup}="";{pack_fallback};{lookup});{pack_fallback})'
            )
        else:
            formulas[qty_addr] = "=0"
            formulas[pack_addr] = f"={pack_fallback}"
    unplaced = tuple(sorted(set(flat_by_sku) - seen_skus))
    return StableSyncPlan(tuple(changes), formulas, unplaced, tuple(stale_mapping), new_line_ids)


def read_stable_sync_plan(client: ZohoSheetAPI, workbook_id: str) -> StableSyncPlan:
    flat = _grid(client, workbook_id, "Flat", "L")
    mapping = _grid(client, workbook_id, "Mapping", "F")
    count = _grid(client, workbook_id, "StockCount", "K")
    return build_stable_sync_plan(flat, mapping, count)
