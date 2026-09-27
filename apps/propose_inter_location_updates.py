"""Export reviewable payment location proposals from the saved Analytics Query Table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_analytics_client
from workflows.core.config import Config
from workflows.inter_location_location_proposals import propose_location_updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--view-id", default="264324000008274019")
    parser.add_argument("--output", type=Path, default=Path("output/inter_location_location_proposals.json"))
    parser.add_argument("--markdown", type=Path, default=Path("output/inter_location_location_proposals.md"))
    args = parser.parse_args()
    for path in (args.output, args.markdown):
        if not path.is_absolute() and (not path.parts or path.parts[0] != "output"):
            parser.error("Relative output must be under output/")
    analytics = get_analytics_client(org_id=Config.ANALYTICS_ORG_ID)
    rows = analytics.views.export_all(args.workspace_id, args.view_id)
    proposals = propose_location_updates(rows)
    report = {"workspace_id": args.workspace_id, "view_id": args.view_id,
              "allocation_rows": len(rows), "pair_count": len(proposals),
              "proposed_pairs": sum(p["status"] == "proposed" for p in proposals),
              "manual_review_pairs": sum(p["status"] == "manual_review" for p in proposals),
              "proposals": proposals}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Inter-location payment location proposals", "",
             f"Source: Zoho Analytics Query Table {args.view_id}; {len(rows)} allocation rows, {len(proposals)} pairs.",
             "", "## Proposed moves", "",
             "| Date | Amount | Customer payment ID | Move from | Move to | Invoice(s) | Bill(s) |",
             "| --- | ---: | --- | --- | --- | --- | --- |"]
    for proposal in proposals:
        for move in proposal["moves"]:
            if proposal["status"] == "proposed":
                lines.append("| " + " | ".join((proposal["date"], proposal["amount"],
                    proposal["customer_payment_id"], move["from_location"], move["to_location"],
                    ", ".join(proposal["invoice_numbers"]), ", ".join(proposal["bill_numbers"]))) + " |")
    lines.extend(["", "## Manual review", "",
                  "| Date | Amount | Customer payment ID | Contra ID | Reason | Invoice location | Bill location |",
                  "| --- | ---: | --- | --- | --- | --- | --- |"])
    for proposal in proposals:
        if proposal["status"] == "manual_review":
            lines.append("| " + " | ".join((proposal["date"], proposal["amount"],
                proposal["customer_payment_id"], proposal["contra_id"], proposal["reason"],
                ", ".join(proposal["invoice_locations"]), ", ".join(proposal["bill_locations"]))) + " |")
    lines.extend(["", "These are proposals only. No Zoho Books locations were changed.", ""])
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(lines), encoding="utf-8")
    print(f"{report['pair_count']} pairs from {len(rows)} allocation rows; "
          f"{report['proposed_pairs']} proposed, {report['manual_review_pairs']} manual review.")
    print(f"Review files: {args.markdown}, {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
