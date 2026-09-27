"""Move reviewed customer payments with destination location number series."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, date
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.inter_location_payment_updates import (
    plan_customer_payment_moves, submit_customer_payment_move, verify_customer_payment_batch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, default=Path("output/inter_location_payment_proposals.json"))
    parser.add_argument("--prefix", default="SB2526CP-")
    parser.add_argument("--financial-year", default="FY 2025-26", choices=["FY 2025-26"])
    parser.add_argument("--last-suffix", type=int, default=None,
                        help="Override the current highest Books suffix; default reads Books")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--exclude-payment-id", action="append", default=["1094368000053835002"])
    parser.add_argument("--audit", type=Path, default=Path("output/inter_location_customer_payment_apply_audit.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = json.loads(args.proposal.read_text(encoding="utf-8"))
    if (report.get("workspace_id"), report.get("view_id")) != (
            "264324000000002043", "264324000008274019"):
        raise ValueError("Proposal is not from the reviewed Query Table")
    proposals = [p for p in report["proposals"]
                 if p.get("financial_year") == args.financial_year
                 and date(2025, 4, 1) <= datetime.strptime(p["date"], "%d/%m/%Y").date()
                 <= date(2026, 3, 31)]
    books = get_books_client()
    moves = plan_customer_payment_moves(books, proposals,
                                        prefix=args.prefix, last_suffix=args.last_suffix,
                                        limit=args.batch_size,
                                        excluded_payment_ids=frozenset(args.exclude_payment_id))
    if not moves:
        raise ValueError("No eligible payments remain in this series")
    if len(moves) != args.batch_size:
        raise ValueError(f"Only {len(moves)} eligible payments; batch size is {args.batch_size}")
    for move in moves:
        print(f"{move['payment_id']}: {move['old_number']} -> {move['new_number']} "
              f"at {move['target_location_id']}")
    if not args.apply:
        print(f"Dry run: {len(moves)} payment(s); no updates applied.")
        return 0
    if not args.audit.is_absolute() and (not args.audit.parts or args.audit.parts[0] != "output"):
        parser.error("Relative audit path must be under output/")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    audit: dict[str, object] = {"planned": moves, "submitted_payment_ids": [], "results": []}
    for move in moves:
        try:
            submit_customer_payment_move(books, move)
            audit["submitted_payment_ids"].append(move["payment_id"])  # type: ignore[union-attr]
        except Exception as exc:
            audit["error"] = f"{move['payment_id']}: {exc}"
            args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
            raise
        args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    try:
        audit["results"] = verify_customer_payment_batch(books, moves)
    except Exception as exc:
        audit["error"] = f"Batch read-back: {exc}"
        args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        raise
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(moves)} payment(s). Audit: {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
