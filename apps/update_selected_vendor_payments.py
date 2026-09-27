"""Update the three reviewed FY 2025-26 IDFC vendor payments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.inter_location_vendor_payment_updates import (
    preflight_vendor_moves, submit_vendor_move, verify_vendor_batch,
)


SOURCE = Path("output/inter_location_vendor_payment_proposals_fy2526.json")
AUDIT = Path("output/inter_location_vendor_payment_selected_apply_audit.json")
SELECTED = {
    "1094368000052246831": "SB2526VP-00067",
    "1094368000050934097": "SB2526VP-00066",
    "1094368000052753739": "SB2526VP-00068",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    if report.get("source_view_id") != "264324000008274019":
        raise ValueError("Unexpected vendor proposal source")
    moves = sorted((m for m in report["moves"] if m["payment_id"] in SELECTED),
                   key=lambda m: m["destination_number"])
    if len(moves) != 3 or any(m["destination_number"] != SELECTED[m["payment_id"]] for m in moves):
        raise ValueError("Selected vendor proposal differs from the reviewed three moves")
    books = get_books_client()
    preflight_vendor_moves(books, moves)
    for move in moves:
        print(f"{move['payment_id']}: {move['old_number']} -> {move['destination_number']}")
    if not args.apply:
        print("Dry run: 3 verified; no vendor payments updated.")
        return 0
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    audit: dict[str, object] = {"planned": moves, "submitted_payment_ids": [], "results": []}
    for move in moves:
        try:
            submit_vendor_move(books, move)
            audit["submitted_payment_ids"].append(move["payment_id"])  # type: ignore[union-attr]
        except Exception as exc:
            audit["error"] = f"{move['payment_id']}: {exc}"
            AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
            raise
        AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    try:
        audit["results"] = verify_vendor_batch(books, moves)
    except Exception as exc:
        audit["error"] = f"Batch read-back: {exc}"
        AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        raise
    AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"Verified 3 vendor payments. Audit: {AUDIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
