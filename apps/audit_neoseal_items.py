#!/usr/bin/env python3
"""Audit Neoseal Books items for duplicates, naming, SKU structure, and groups."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.neoseal_audit import audit_neoseal_items, render_markdown_report


def load_items_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load items from a local exported inventory CSV."""
    with csv_path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purchase-account-id",
        default=Config.NEOSEAL_PURCHASE_ACCOUNT_ID,
        help="Zoho Books purchase account ID for Neoseal stock",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="Optional local CSV inventory snapshot to audit instead of querying Books API",
    )
    parser.add_argument(
        "--status",
        default="all",
        choices=["active", "inactive", "all"],
        help="Item status filter when querying Zoho Books (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/neoseal_item_audit.md"),
        help="Path for generated Markdown audit report",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write structured JSON audit results",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input_csv:
        if not args.input_csv.exists():
            print(f"Error: Input CSV '{args.input_csv}' does not exist.", file=sys.stderr)
            return 1
        items = load_items_from_csv(args.input_csv)
        source_label = f"Local CSV ({args.input_csv.name})"
    else:
        if not args.purchase_account_id:
            print(
                "Error: Neither --input-csv nor --purchase-account-id was provided. "
                "Set NEOSEAL_PURCHASE_ACCOUNT_ID in config or pass as argument.",
                file=sys.stderr,
            )
            return 2
        books = get_books_client()
        items = books.items.list_by_purchase_account(
            args.purchase_account_id,
            status=args.status,
        )
        source_label = f"Zoho Books API (Purchase Account: {args.purchase_account_id}, Status: {args.status})"

    result = audit_neoseal_items(items)

    metadata = {
        "source": source_label,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Write Markdown report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_content = render_markdown_report(result, metadata)
    args.output.write_text(report_content, encoding="utf-8")

    # Write JSON output if requested
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": metadata,
            "result": result,
        }
        args.json_output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(
        f"Audited {result['total_audited']} items. "
        f"Duplicates: {len(result['duplicates'])}, "
        f"Naming issues: {len(result['naming_issues'])}, "
        f"SKU issues: {len(result['sku_issues'])}, "
        f"Group issues: {len(result['group_issues'])}. "
        f"Report written to '{args.output}'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
