#!/usr/bin/env python3
"""Upsert active, inventory-tracked Neoseal items into the Flat Zoho Sheet tab."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_inventory_client, get_sheet_client
from workflows.core.config import Config
from workflows.neoseal_stock_count import (
    delete_approved_missing_flat_items,
    fetch_neoseal_flat_stock,
    upsert_flat_stock_to_sheet,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purchase-account-id", default=Config.NEOSEAL_PURCHASE_ACCOUNT_ID)
    parser.add_argument("--location-id", help="Optional Inventory location ID; default is whole organization")
    parser.add_argument("--sheet-id", default=Config.NEOSEAL_STOCK_COUNT_SHEET_ID)
    parser.add_argument("--flat-worksheet", default=Config.NEOSEAL_STOCK_COUNT_FLAT_WORKSHEET)
    parser.add_argument("--delete-missing-item-id", action="append", default=[],
                        help="Delete one previously reviewed missing Flat item ID; repeat for more IDs")
    args = parser.parse_args(argv)
    if not args.purchase_account_id or not args.purchase_account_id.strip():
        parser.error("Set NEOSEAL_PURCHASE_ACCOUNT_ID or pass --purchase-account-id.")
    if any(not item_id.isdigit() for item_id in args.delete_missing_item_id):
        parser.error("--delete-missing-item-id requires a numeric item ID.")
    try:
        if not args.sheet_id or not args.sheet_id.strip():
            parser.error("Set NEOSEAL_STOCK_COUNT_SHEET_ID or pass --sheet-id.")
        snapshot = fetch_neoseal_flat_stock(
            get_inventory_client(),
            purchase_account_id=args.purchase_account_id,
            location_id=args.location_id,
        )
        sheet_client = get_sheet_client()
        result = upsert_flat_stock_to_sheet(
            sheet_client,
            workbook_id=args.sheet_id,
            worksheet_name=args.flat_worksheet,
            snapshot=snapshot,
        )
        deleted = 0
        if args.delete_missing_item_id:
            deleted = delete_approved_missing_flat_items(
                sheet_client,
                workbook_id=args.sheet_id,
                worksheet_name=args.flat_worksheet,
                snapshot=snapshot,
                approved_item_ids=args.delete_missing_item_id,
            )
    except Exception as exc:
        print(f"Stock count failed: {exc}", file=sys.stderr)
        return 1
    print(f"Listed {len(snapshot.rows)} items; {sum(bool(r.warnings) for r in snapshot.rows)} rows need review.")
    print(f"Zoho Sheet updated: {args.sheet_id} / {result.worksheet_name}")
    if deleted:
        print(f"Deleted {deleted} approved missing Flat item(s).")
    approved = set(args.delete_missing_item_id)
    remaining = [item for item in result.missing_items if item.item_id not in approved]
    if remaining:
        print(f"Flat items absent from the current active, inventory-tracked bulk fetch ({len(remaining)}):")
        for item in remaining:
            print(f"- {item.item_id} | {item.sku} | {item.name}")
        print("Deletion requires approval for these exact item IDs; no other rows were deleted.")
    else:
        print("No unapproved Flat items are missing from the current bulk fetch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
