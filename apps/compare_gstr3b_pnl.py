#!/usr/bin/env python3
"""Compare a full-year GSTR-3B JSON with Zoho Books Sales and P&L COGS."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.gstr3b_pnl_comparison import (
    ComparisonConfig, compare_gstr3b_to_pnl, write_comparison_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path, help="Combined GSTR-3B JSON with 12 filed returns")
    parser.add_argument("--sales-account-id", default="1094368000000000486",
                        help="Root Sales account ID; includes every descendant account")
    parser.add_argument("--exclude-location-id", default="1094368000044509446",
                        help="Books branch/location ID excluded from the P&L")
    parser.add_argument("--org-id", default=Config.ORG_ID, help="Zoho Books organization ID")
    parser.add_argument("--domain", default=Config.DOMAIN, help="Zoho data-center domain")
    parser.add_argument("--tolerance", default="1.00", help="Sales variance tolerance in INR")
    parser.add_argument("--output", type=Path, help="CSV output (default: output/gstr3b_vs_books_pnl_<FY>.csv)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = json.loads(args.json_file.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("GSTR-3B JSON must contain an object")
        config = ComparisonConfig(
            sales_account_id=args.sales_account_id,
            excluded_location_id=args.exclude_location_id,
            tolerance=Decimal(args.tolerance),
        )
        books = get_books_client(org_id=args.org_id, domain=args.domain)
        rows = compare_gstr3b_to_pnl(books, data, config)
        fy = str(data["filing_year"])
        output = args.output or Path("output") / f"gstr3b_vs_books_pnl_{fy}.csv"
        write_comparison_csv(rows, output)
    except (OSError, ValueError, KeyError, InvalidOperation, json.JSONDecodeError) as exc:
        print(f"Comparison failed: {exc}", file=sys.stderr)
        return 1
    annual = rows[-1]
    differences = [row["period"] for row in rows[:-1] if row["sales_comparison"] == "DIFFERENCE"]
    print(f"Generated: {output}")
    print(f"Checked at: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    print(f"FY Books Sales: {annual['books_sales_total']}; GSTR-3B taxable: "
          f"{annual['gstr3b_outward_taxable_value']}; Books minus GSTR-3B: "
          f"{annual['sales_variance_books_minus_gstr3b']}")
    print(f"Months with sales differences: {', '.join(differences) if differences else 'none'}")
    print("Purchase comparison unavailable: GSTR-3B has no ordinary purchase total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
