#!/usr/bin/env python3
"""Synchronize customer contacts between Zoho Books and Zoho Creator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.config import Config
from workflows.creator_customer_sync import CreatorCustomerSyncConfig, sync_creator_customers


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-link-name",
        default=Config.PAYMENT_CREATOR_APP_LINK_NAME,
        help="Zoho Creator application link name (default: %(default)s)",
    )
    parser.add_argument(
        "--report-link-name",
        default=Config.PAYMENT_CREATOR_REPORTS.get("customer", "All_Customers1"),
        help="Zoho Creator customer report link name (default: %(default)s)",
    )
    parser.add_argument(
        "--form-link-name",
        default="Customer_Registration",
        help="Zoho Creator customer form link name for creates (default: %(default)s)",
    )
    parser.add_argument(
        "--branch",
        default="Electricals",
        help="Filter Books customers by branch name; use 'all' for no branch filter (default: %(default)s)",
    )
    parser.add_argument(
        "--status",
        choices=["all", "active", "inactive"],
        default="all",
        help="Filter Books customers by status (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory to save sync audit report JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--max-deletion-limit",
        type=int,
        default=50,
        help="Maximum allowed candidate deletions before aborting (default: %(default)s)",
    )
    parser.add_argument(
        "--max-deletion-percentage",
        type=float,
        default=15.0,
        help="Maximum allowed deletion percentage before aborting (default: %(default)s%%)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate sync without mutating Zoho Creator (default)",
    )
    mode_group.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Apply changes live to Zoho Creator",
    )

    args = parser.parse_args(argv)
    branch = None if args.branch.strip().lower() == "all" else args.branch.strip()

    config = CreatorCustomerSyncConfig(
        app_link_name=args.app_link_name,
        report_link_name=args.report_link_name,
        form_link_name=args.form_link_name,
        creator_id_field="Customer_Id",
        books_id_field="contact_id",
        books_status_filter=args.status,
        books_branch_name=branch,
        field_mapping={"Name": "contact_name"},
        dry_run=args.dry_run,
        max_deletion_limit=args.max_deletion_limit,
        max_deletion_percentage=args.max_deletion_percentage,
        output_dir=args.output_dir,
    )

    mode_label = "DRY-RUN (Simulated)" if config.dry_run else "LIVE (Mutating)"
    print(f"Starting Creator Customer Sync [{mode_label}]...")
    print(f"  App: {config.app_link_name} | Report: {config.report_link_name} | Form: {config.form_link_name}")
    print(f"  Branch filter: {branch or 'All'} | Status filter: {config.books_status_filter}")

    try:
        books_client = get_books_client()
        creator_client = get_creator_client()
        summary = sync_creator_customers(books_client, creator_client, config)
    except Exception as exc:
        print(f"Customer sync failed: {exc}", file=sys.stderr)
        return 1

    print("\nSync Results:")
    print(f"  Scanned Books customers:   {summary.get('scanned_books_customer_keys_count', 0)}")
    print(f"  Scanned Creator records:   {summary.get('scanned_creator_records_count', 0)}")
    print(f"  Matched records:           {summary.get('matched_records_count', 0)}")
    print(f"  Unchanged records:         {summary.get('unchanged_count', 0)}")
    print(f"  Candidate creates:         {summary.get('candidate_create_count', 0)}")
    print(f"  Candidate updates:         {summary.get('candidate_update_count', 0)}")
    print(f"  Candidate deletes:         {summary.get('candidate_delete_count', 0)}")
    if not config.dry_run:
        print(f"  Created records:           {summary.get('created_count', 0)}")
        print(f"  Updated records:           {summary.get('updated_count', 0)}")
        print(f"  Deleted records:           {summary.get('deleted_count', 0)}")
    print(f"  Report written to:         {summary.get('report_file')}")

    # List any candidates if present
    records = summary.get("records", [])
    if records:
        print(f"\nPlanned Changes ({len(records)}):")
        for rec in records[:15]:
            op = rec.get("operation")
            key = rec.get("customer_key")
            name = rec.get("payload", {}).get("Name", "")
            print(f"  [{op}] Customer ID {key}: {name}")
        if len(records) > 15:
            print(f"  ... and {len(records) - 15} more (see report file)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
