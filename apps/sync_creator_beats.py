#!/usr/bin/env python3
"""Sync beats assigned in Zoho Creator to Zoho Books customer contacts."""

from __future__ import annotations

import argparse
import sys

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.config import Config
from workflows.creator_beat_sync import sync_creator_beats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-link-name", default=Config.PAYMENT_CREATOR_APP_LINK_NAME)
    parser.add_argument("--report-link-name", default=Config.PAYMENT_CREATOR_REPORTS.get("customer", "All_Customers1"))
    parser.add_argument("--books-field", default="cf_beat", help="Books contact custom field API name")
    parser.add_argument("--apply", action="store_true", help="Write the previewed changes to Books")
    parser.add_argument("--show-all", action="store_true", help="Print every changed customer (default: first 20)")
    args = parser.parse_args()
    try:
        result = sync_creator_beats(
            get_books_client(), get_creator_client(), args.app_link_name,
            args.report_link_name, books_field=args.books_field, apply=args.apply,
        )
    except Exception as exc:
        print(f"Beat sync failed: {exc}", file=sys.stderr)
        return 1
    print(f"Creator records: {result['scanned']}; unassigned: {result['skipped_unassigned']}; "
          f"inactive: {result['skipped_inactive']}; unchanged: {result['unchanged']}")
    shown = result["changes"] if args.show_all else result["changes"][:20]
    for change in shown:
        print(f"{change['books_id']} {change['customer']}: {change['current'] or '(blank)'} -> {change['beat']}")
    if len(shown) < len(result["changes"]):
        print(f"... {len(result['changes']) - len(shown)} more; use --show-all to list every change")
    print(f"{'Updated' if args.apply else 'Would update'}: {result['updated'] if args.apply else len(result['changes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
