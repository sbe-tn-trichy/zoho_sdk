#!/usr/bin/env python3
"""Sync stable line IDs, Mapping addresses, and StockCount formulas via Zoho Sheet API."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_sheet_client
from workflows.core.config import Config
from workflows.neoseal_stock_count.stable_sync import StableSyncPlan, read_stable_sync_plan


def formula_audit(sheet, workbook: str, cells: Sequence[str]) -> dict[str, str]:
    """Read stored expressions through Zoho's FORMULA function in an empty probe cell."""
    probe = sheet.request("GET", workbook, params={
        "method": "worksheet.content.get", "worksheet_name": "StockCount", "range": "L1",
    })
    if probe.get("range_details"):
        raise ValueError("StockCount L1 must be empty for formula introspection")
    found: dict[str, str] = {}
    try:
        for start in range(0, len(cells), 12):
            batch = cells[start:start + 12]
            expression = "=" + '&"♦"&'.join(f'IFERROR(FORMULA({cell});"")' for cell in batch)
            response = sheet.set_cell(workbook, "StockCount", 1, 12, expression)
            parts = str(response["cell"]["cell_value"]).split("♦")
            if len(parts) != len(batch):
                raise ValueError(f"Formula audit response count differs at {batch[0]}")
            found.update(zip(batch, parts))
            time.sleep(1.25)
    finally:
        sheet.clear_range(workbook, "StockCount", 1, 12, 1, 12)
    return found


def apply_plan(sheet, workbook: str, plan: StableSyncPlan) -> int:
    addresses = list(plan.formulas)
    before = formula_audit(sheet, workbook, addresses)
    formula_changes = {cell: value for cell, value in plan.formulas.items() if before[cell] != value}
    print(f"Helper/address writes: {len(plan.changes)}; formula writes: {len(formula_changes)}", flush=True)
    for index, change in enumerate(plan.changes, 1):
        sheet.set_cell(workbook, change.sheet, change.row, change.column, change.content)
        if index % 25 == 0:
            print(f"Applied {index}/{len(plan.changes)} helper/address writes", flush=True)
        time.sleep(1.25)
    for index, (address, formula) in enumerate(formula_changes.items(), 1):
        row = int(address[1:])
        column = ord(address[0]) - 64
        sheet.set_cell(workbook, "StockCount", row, column, formula)
        if index % 25 == 0:
            print(f"Applied {index}/{len(formula_changes)} formula writes", flush=True)
        time.sleep(1.25)
    after = formula_audit(sheet, workbook, addresses)
    bad = [cell for cell in addresses if after[cell] != plan.formulas[cell]]
    if bad:
        raise ValueError(f"Stored formulas differ: {bad[:10]}")
    print(f"Verified {len(addresses)} stored formulas", flush=True)
    return len(formula_changes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", default=Config.NEOSEAL_STOCK_COUNT_SHEET_ID)
    parser.add_argument("--apply", action="store_true", help="Write plan via Zoho Sheet API")
    args = parser.parse_args(argv)
    try:
        sheet = get_sheet_client()
        plan = read_stable_sync_plan(sheet, args.sheet_id)
        print(f"Product lines: {len(plan.formulas)//2}; new IDs: {plan.new_line_ids}; "
              f"unplaced Flat SKUs: {len(plan.unplaced_skus)}; "
              f"stale unmapped Mapping SKUs: {len(plan.stale_mapping_skus)}", flush=True)
        for sku in plan.unplaced_skus:
            print(f"Unplaced: {sku}", flush=True)
        for sku in plan.stale_mapping_skus:
            print(f"Stale unmapped Mapping row: {sku}", flush=True)
        if args.apply:
            apply_plan(sheet, args.sheet_id, plan)
    except Exception as exc:
        print(f"Stable sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
