"""Verify GSTR-1 readiness using Analytics, or live Books on force refresh."""

import argparse
import json
from pathlib import Path

from workflows.core.auth import get_analytics_client, get_books_client
from workflows.core.config import Config
from workflows.gstr1_verification import GSTR1VerificationConfig, verify_gstr1, render_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", help="Return month YYYY-MM; defaults to previous month")
    parser.add_argument("--force-refresh", action="store_true", help="Fetch live Zoho Books data")
    parser.add_argument("--analytics-workspace-id", default="264324000000002043")
    parser.add_argument("--no-e-invoice", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("output/gstr1_verification.md"),
                        help="Markdown report path")
    parser.add_argument("--json-output", type=Path, help="Also save the structured JSON result")
    args = parser.parse_args()
    report = verify_gstr1(
        books_client=get_books_client() if args.force_refresh else None,
        analytics_client=get_analytics_client(),
        analytics_workspace_id=args.analytics_workspace_id,
        month=args.month, force_refresh=args.force_refresh,
        config=GSTR1VerificationConfig(e_invoice_applicable=not args.no_e_invoice,
                                      financial_credit_note_ids=tuple(Config.GSTR1_FINANCIAL_CREDIT_NOTES)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown_report(report, gstin_aliases=Config.GSTIN_ALIASES), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"GSTR-1 report ({report['data_source']}): {args.output}")
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
