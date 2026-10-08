#!/usr/bin/env python3
"""Fill Creator Customer# from Books for explicitly selected linked customers."""
import argparse
from dataclasses import asdict
import json

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.customer_registration import sync_customer_numbers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books-contact-id", action="append", required=True, help="Books customer ID; repeat for multiple customers.")
    parser.add_argument("--app", default="order-management-new")
    parser.add_argument("--report", default="All_Customers1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Save and verify the proposed number updates.")
    mode.add_argument("--dry-run", action="store_true", help="Preview updates (default).")
    args = parser.parse_args()
    result = sync_customer_numbers(
        get_books_client(), get_creator_client(), args.books_contact_id,
        app_link_name=args.app, report_link_name=args.report, dry_run=not args.apply,
    )
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
