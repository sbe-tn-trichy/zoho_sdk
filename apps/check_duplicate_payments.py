#!/usr/bin/env python3
"""Check Zoho Books for duplicate customer payments; never modifies Books."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.duplicate_payment_check import (
    check_duplicate_payments,
    render_html_report,
    render_markdown_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-id", help="Limit the check to one Books customer ID")
    parser.add_argument("--from-date", help="Include payments on or after YYYY-MM-DD")
    parser.add_argument("--to-date", help="Include payments on or before YYYY-MM-DD")
    parser.add_argument("--org-id", default=Config.ORG_ID, help="Zoho Books organization ID")
    parser.add_argument("--domain", default=Config.DOMAIN, help="Zoho data-center domain")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/duplicate_customer_payments.md"),
        help="Readable Markdown report path; use an .html suffix for the interactive table",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    books = get_books_client(org_id=args.org_id, domain=args.domain)
    result = check_duplicate_payments(
        books,
        customer_id=args.customer_id,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": args.org_id,
        "filters": {
            "customer_id": args.customer_id,
            "from_date": args.from_date,
            "to_date": args.to_date,
        },
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = render_html_report(payload) if args.output.suffix.lower() == ".html" else render_markdown_report(payload)
    args.output.write_text(report, encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
