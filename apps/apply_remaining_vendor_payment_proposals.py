"""Apply the current FY 2025-26 vendor-payment proposals after full preflight."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.inter_location_vendor_payment_updates import (
    preflight_vendor_moves, submit_vendor_move, verify_vendor_batch,
)


SOURCE = Path("output/inter_location_payment_proposals.json")
NUMBERED = Path("output/inter_location_vendor_payment_proposals_fy2526.json")
AUDIT = Path("output/inter_location_vendor_payment_remaining_apply_audit.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    proposal = json.loads(SOURCE.read_text(encoding="utf-8"))
    numbered = json.loads(NUMBERED.read_text(encoding="utf-8"))
    if (proposal.get("view_id"), proposal.get("financial_year"),
            numbered.get("source_view_id")) != (
            "264324000008274019", "FY 2025-26", "264324000008274019"):
        raise ValueError("Unexpected proposal source")
    candidates = {str(row["payment_id"]): row for row in proposal["proposals"]
                  if row["status"] == "proposed" and row["payment_type"] == "Vendor Payment"}
    moves = numbered["moves"]
    if (not candidates or len(candidates) != len(moves)
            or {str(move["payment_id"]) for move in moves} != set(candidates)
            or numbered.get("held_count") != 0):
        raise ValueError("Numbered moves do not exactly match current proposed vendor payments")
    for move in moves:
        row = candidates[move["payment_id"]]
        if (move["from_location_id"] != row["from_location_id"]
                or move["to_location_id"] != row["to_location_id"]
                or move["bank_account_id"] != row["bank_account_id"]
                or move["bill_numbers"] != row["document_numbers"]
                or not move["destination_number"].startswith(row["expected_number_prefix"])):
            raise ValueError(f"Numbered move differs from current proposal: {move['payment_id']}")
    groups: dict[str, list[dict]] = defaultdict(list)
    for move in moves:
        groups[move["destination_number"].rsplit("-", 1)[0]].append(move)
    books = get_books_client()
    for prefix in sorted(groups):
        preflight_vendor_moves(books, groups[prefix])
    print(f"Preflight passed: {len(moves)} vendor payments in {len(groups)} destination series.")
    if not args.apply:
        print("Dry run: no Books changes.")
        return 0
    audit: dict[str, object] = {"planned": moves, "submitted_payment_ids": [], "results": []}
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    for prefix in sorted(groups):
        group = sorted(groups[prefix], key=lambda move: move["destination_number"])
        for move in group:
            try:
                submit_vendor_move(books, move)
                audit["submitted_payment_ids"].append(move["payment_id"])
            except Exception as exc:
                audit["error"] = f"Submit {move['payment_id']}: {exc}"
                AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
                raise
            AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        try:
            audit["results"].extend(verify_vendor_batch(books, group))
        except Exception as exc:
            audit["error"] = f"Verify {prefix}: {exc}"
            AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
            raise
        AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(audit['results'])} vendor payments. Audit: {AUDIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
