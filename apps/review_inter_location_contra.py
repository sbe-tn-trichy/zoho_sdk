"""Export a read-only review of inter-location contra entries or bank payment location mismatches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_analytics_client, get_books_client
from workflows.core.config import Config
from workflows.inter_location_contra import (
    add_analytics_location_evidence,
    fetch_account_entries,
    review_bank_payment_locations,
    review_contras,
    review_source_documents,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", default="1094368000002033114")
    parser.add_argument(
        "--mode",
        choices=["auto", "contra", "bank"],
        default="auto",
        help="Review mode: 'contra' (4-way check for clearing accounts), 'bank' (payment vs document check for regular bank accounts), or 'auto'",
    )
    parser.add_argument("--output", type=Path, default=Path("output/inter_location_contra_review.json"))
    parser.add_argument("--analytics", action="store_true", help="Cross-check against CustomerPaymentLocationDiff")
    parser.add_argument("--analytics-org-id", default=Config.ANALYTICS_ORG_ID)
    parser.add_argument("--analytics-workspace-id", default="264324000000002043")
    parser.add_argument("--location-diff-view-id", default="264324000006990003")
    args = parser.parse_args()
    if not args.output.is_absolute() and args.output.parts[0] != "output":
        parser.error("Relative output must be under output/")
    
    books = get_books_client()
    mode = args.mode
    if mode == "auto":
        mode = "contra" if args.account_id == "1094368000002033114" else "bank"

    if mode == "contra":
        result = review_contras(fetch_account_entries(books, args.account_id))
        result["account_id"] = args.account_id
        review_source_documents(books, result)
        if args.analytics:
            analytics = get_analytics_client(org_id=args.analytics_org_id)
            rows = analytics.views.export_all(args.analytics_workspace_id, args.location_diff_view_id)
            add_analytics_location_evidence(result, rows)
        result["periods"] = ["2025-04-01 to 2026-03-31", "2026-04-01 to 2027-03-31"]
        proposed = sum(pair.get("proposed_move") is not None for pair in result["inter_location_contras"])
        print(f"Reviewed {len(result['transactions'])} entries; {len(result['same_location_contras'])} same-location pairs; {len(result['inter_location_contras'])} inter-location pairs; {proposed} proposed moves; {len(result['ambiguous'])} ambiguous groups.")
    else:
        result = review_bank_payment_locations(books, args.account_id)
        result["periods"] = ["2025-04-01 to 2026-03-31", "2026-04-01 to 2027-03-31"]
        print(f"Reviewed {result['total_entries']} entries ({result['audited_payments']} payments); {len(result['mismatches'])} document location mismatches found.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Review file: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
