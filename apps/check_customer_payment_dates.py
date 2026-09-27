#!/usr/bin/env python3
"""Check customer payments for mismatches between payment date and applied dates using Zoho Analytics."""

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

from workflows.core.auth import get_analytics_client
from workflows.core.config import Config
from workflows.customer_payment_date_check import (
    check_customer_payment_dates_analytics,
    render_csv_report,
    render_markdown_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-id", help="Limit the check to one customer ID")
    parser.add_argument("--from-date", help="Include payments on or after YYYY-MM-DD")
    parser.add_argument("--to-date", help="Include payments on or before YYYY-MM-DD")
    parser.add_argument("--tolerance-days", type=int, default=0, help="Allowed difference in days (default: 0)")
    parser.add_argument("--workspace-id", default="264324000000002043", help="Zoho Analytics workspace ID")
    parser.add_argument("--view-id", default="264324000008269008", help="Query Table view ID in Zoho Analytics")
    parser.add_argument("--org-id", default=Config.ANALYTICS_ORG_ID, help="Zoho Analytics organization ID")
    parser.add_argument("--domain", default=Config.DOMAIN, help="Zoho data-center domain")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/customer_payment_date_mismatches.md"),
        help="Report path (.md, .csv, or .json)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    analytics = get_analytics_client(org_id=args.org_id, domain=args.domain)
    result = check_customer_payment_dates_analytics(
        analytics,
        workspace_id=args.workspace_id,
        view_id=args.view_id,
        customer_id=args.customer_id,
        from_date=args.from_date,
        to_date=args.to_date,
        tolerance_days=args.tolerance_days,
    )
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": args.workspace_id,
        "view_id": args.view_id,
        "filters": {
            "customer_id": args.customer_id,
            "from_date": args.from_date,
            "to_date": args.to_date,
            "tolerance_days": args.tolerance_days,
        },
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    suffix = args.output.suffix.lower()
    if suffix == ".json":
        args.output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    elif suffix == ".csv":
        args.output.write_text(render_csv_report(payload), encoding="utf-8")
    else:
        args.output.write_text(render_markdown_report(payload), encoding="utf-8")

    print(
        f"Scanned {result['payments_scanned']} payments from Analytics view {args.view_id}. "
        f"Found {result['mismatched_payments_count']} payments with "
        f"{result['total_mismatched_applications']} date-mismatched invoice allocations."
    )
    print(f"Report written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
