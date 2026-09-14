#!/usr/bin/env python3
"""Create grouped Neoseal stock-count sheets using Zoho Inventory."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_inventory_client, get_sheet_client
from workflows.core.config import Config
from workflows.neoseal_stock_count import (
    CountPlacement,
    fetch_neoseal_stock_count,
    fill_quantities_from_mapping,
    write_flat_stock_count_to_sheet,
    write_mapping_to_sheet,
    write_stock_count_to_sheet,
)


def load_layout(path: Path) -> dict[str, CountPlacement]:
    """Read item_id, group, subgroup and optional numeric ordering columns."""
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"item_id", "group", "subgroup"}.issubset(reader.fieldnames or []):
            raise ValueError("Layout CSV requires item_id, group, and subgroup columns.")
        for row in reader:
            item_id = (row["item_id"] or "").strip()
            if not item_id or item_id in result:
                raise ValueError("Layout item IDs must be non-empty and unique.")
            result[item_id] = CountPlacement((row["group"] or "").strip(), (row["subgroup"] or "").strip(),
                int(row.get("group_order") or 90), int(row.get("subgroup_order") or 90),
                int(row.get("item_order") or 0))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purchase-account-id", default=Config.NEOSEAL_PURCHASE_ACCOUNT_ID)
    parser.add_argument("--location-id", help="Optional Inventory location ID; default is whole organization")
    parser.add_argument("--sheet-id", default=Config.NEOSEAL_STOCK_COUNT_SHEET_ID)
    parser.add_argument("--worksheet", default="Sheet1")
    parser.add_argument("--flat-worksheet", default="Flat")
    parser.add_argument("--mapping-worksheet", default="Mapping")
    parser.add_argument("--layout-csv", type=Path, help="Optional shelf layout and count-order overrides")
    args = parser.parse_args(argv)
    if not args.purchase_account_id or not args.purchase_account_id.strip():
        parser.error("Set NEOSEAL_PURCHASE_ACCOUNT_ID or pass --purchase-account-id.")
    try:
        layout = load_layout(args.layout_csv) if args.layout_csv else None
        if not args.sheet_id or not args.sheet_id.strip():
            parser.error("Set NEOSEAL_STOCK_COUNT_SHEET_ID or pass --sheet-id.")
        count = fetch_neoseal_stock_count(
            get_inventory_client(),
            purchase_account_id=args.purchase_account_id,
            location_id=args.location_id,
            layout=layout,
        )
        sheet_client = get_sheet_client()
        flat_result = write_flat_stock_count_to_sheet(
            sheet_client,
            workbook_id=args.sheet_id,
            worksheet_name=args.flat_worksheet,
            count_worksheet_name=args.worksheet,
            count=count,
        )
        result = write_stock_count_to_sheet(
            sheet_client,
            workbook_id=args.sheet_id,
            worksheet_name=args.worksheet,
            count=count,
        )
        mapping_result = write_mapping_to_sheet(
            sheet_client,
            workbook_id=args.sheet_id,
            worksheet_name=args.mapping_worksheet,
            count=count,
            count_worksheet_name=args.worksheet,
        )
        fill_quantities_from_mapping(
            sheet_client,
            workbook_id=args.sheet_id,
            count_worksheet_name=args.worksheet,
            count=count,
            mapping_worksheet_name=args.mapping_worksheet,
            only_custom=True,
        )
    except Exception as exc:
        print(f"Stock count failed: {exc}", file=sys.stderr)
        return 1
    print(f"Listed {len(count.rows)} items in {len({r.placement.group for r in count.rows})} groups; "
          f"{sum(bool(r.warnings) for r in count.rows)} rows need review.")
    print(f"Zoho Sheet updated: {args.sheet_id} / {result.worksheet_name}, {flat_result.worksheet_name}, and {mapping_result.worksheet_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
