#!/usr/bin/env python3
"""Format and align cell merges and borders in the Neoseal stock count worksheet."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_sheet_client
from workflows.core.config import Config
from workflows.neoseal_stock_count import format_custom_stock_count_sheet


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", default=Config.NEOSEAL_STOCK_COUNT_SHEET_ID)
    parser.add_argument("--worksheet", default=Config.NEOSEAL_STOCK_COUNT_WORKSHEET)
    args = parser.parse_args(argv)

    if not args.sheet_id or not args.sheet_id.strip():
        parser.error("Set NEOSEAL_STOCK_COUNT_SHEET_ID or pass --sheet-id.")
    if not args.worksheet or not args.worksheet.strip():
        parser.error("Set NEOSEAL_STOCK_COUNT_WORKSHEET or pass --worksheet.")

    try:
        sheet_client = get_sheet_client()
        result = format_custom_stock_count_sheet(
            sheet_client,
            workbook_id=args.sheet_id,
            worksheet_name=args.worksheet,
        )
    except Exception as exc:
        print(f"Formatting failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Successfully formatted {result['rule_count']} range rules in {args.sheet_id} / {args.worksheet}."
    )
    print(
        f"Merged {result['merged_headers_count']} category headers across table columns with clean borders."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
