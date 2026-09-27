#!/usr/bin/env python3
"""Apply or preview invoice payment date updates to greatest(Payment Date, Invoice Date)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.customer_payment_date_check import (
    CustomerPaymentDateUpdater,
    build_update_plan,
    render_plan_markdown,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT_DIR / "output" / "invoice_payment_date_update_plan.json",
        help="Path to precomputed plan JSON",
    )
    parser.add_argument(
        "--recompute-plan",
        action="store_true",
        help="Force recomputing plan from output/customer_payment_date_mismatches.json",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform live updates in Zoho Books (default is dry-run preview)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=ROOT_DIR / "output" / "invoice_payment_date_update_checkpoint.json",
        help="Path to save execution checkpoint JSON",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    audit_file = ROOT_DIR / "output" / "customer_payment_date_mismatches.json"

    if args.recompute_plan or not args.plan.exists():
        if not audit_file.exists():
            sys.exit(f"Error: Audit file {audit_file} not found. Run apps/check_customer_payment_dates.py first.")
        audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        plan = build_update_plan(audit_data)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        args.plan.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        plan_md = args.plan.with_suffix(".md")
        plan_md.write_text(render_plan_markdown(plan), encoding="utf-8")
        print(f"Plan generated ({plan['total_discrepancies']} allocations across {plan['distinct_payments_count']} payments) and saved to {args.plan}")
    else:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    books = get_books_client()
    updater = CustomerPaymentDateUpdater(books)

    result = updater.execute_plan(
        plan,
        execute=args.execute,
        checkpoint_path=args.checkpoint,
    )

    summary = result["summary"]
    mode_str = "LIVE EXECUTION" if args.execute else "DRY-RUN PREVIEW"
    print(f"=== {mode_str} SUMMARY ===")
    print(f"Total Payments: {summary['total_payments']}")
    if args.execute:
        print(f"Successfully Updated: {summary['updated']}")
        print(f"Failed: {summary['failed']}")
    else:
        print(f"Planned: {summary['planned']}")
        print("Run with --execute to apply updates to Zoho Books.")

    print(f"Checkpoint saved to: {args.checkpoint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
