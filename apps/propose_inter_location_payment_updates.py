"""Export reviewable payment location proposals from the all-bank-account Analytics QT."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_analytics_client
from workflows.core.config import Config
from workflows.inter_location_payment_proposals import (
    allocation_summary_query, filter_payment_rows_for_year, propose_payment_locations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--view-id", default="264324000008274019")
    parser.add_argument("--output", type=Path, default=Path("output/inter_location_payment_proposals.json"))
    parser.add_argument("--markdown", type=Path, default=Path("output/inter_location_payment_proposals.md"))
    args = parser.parse_args()
    for path in (args.output, args.markdown):
        if not path.is_absolute() and (not path.parts or path.parts[0] != "output"):
            parser.error("Relative output must be under output/")
    analytics = get_analytics_client(org_id=Config.ANALYTICS_ORG_ID)
    rows = filter_payment_rows_for_year(
        analytics.views.export_all(args.workspace_id, args.view_id), "FY 2025-26")
    summaries = {}
    for payment_type in ("Customer Payment", "Vendor Payment"):
        summaries[payment_type] = {
            str(row["Payment ID"]): row for row in analytics.queries.execute(
                args.workspace_id, allocation_summary_query(payment_type))
        }
    proposals = propose_payment_locations(rows, summaries)
    counts = Counter(proposal["status"] for proposal in proposals)
    report = {"workspace_id": args.workspace_id, "view_id": args.view_id,
              "financial_year": "FY 2025-26",
              "payment_count": len(proposals), "status_counts": dict(counts), "proposals": proposals}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# FY 2025–26 inter-location payment location proposals", "",
             f"Source: Analytics Query Table {args.view_id}. Payments: {len(proposals)}; "
             f"proposed: {counts['proposed']}; manual review: {counts['manual_review']}.", "",
             "All allocated document locations were checked in Analytics. Verify current Zoho Books "
             "payment, document, and destination number-series state before applying a move. "
             "The shown prefix is observed from existing payments; assign a free suffix in Books.", "",
             "| Status | Bank account | Payment type | Payment ID | Date | Amount | From | To | Number prefix | Documents | Reason |",
             "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |"]
    for proposal in proposals:
        values = (proposal["status"], proposal["bank_account_name"], proposal["payment_type"],
                  proposal["payment_id"], proposal["date"], proposal["amount"],
                  proposal["from_location"], proposal["to_location"],
                  proposal["expected_number_prefix"],
                  ", ".join(proposal["document_numbers"]), proposal["reason"])
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(["", "No Zoho Books locations were changed.", ""])
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(proposals)} payments: {counts['proposed']} proposed, {counts['manual_review']} manual review.")
    print(f"Reports: {args.markdown}, {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
