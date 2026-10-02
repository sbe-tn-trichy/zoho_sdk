#!/usr/bin/env python3
"""Preview or update one Zoho Books bill's transaction posting date."""

from __future__ import annotations

import argparse

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.bill_updates import update_bill_transaction_posting_date
from workflows.core.auth import get_books_client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bill_id", help="Zoho Books bill ID")
    parser.add_argument("posting_date", help="New transaction posting date (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true", help="Save the changed date in Zoho Books")
    args = parser.parse_args()

    books = get_books_client()
    result = update_bill_transaction_posting_date(
        books, args.bill_id, args.posting_date, dry_run=not args.apply,
    )
    if result.previous_date == result.requested_date:
        print(f"Bill {result.bill_id}: already {result.requested_date}; no update needed.")
    elif result.dry_run:
        print(f"Bill {result.bill_id}: would change {result.previous_date} to {result.requested_date}.")
    else:
        print(f"Bill {result.bill_id}: updated {result.previous_date} to {result.requested_date}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
