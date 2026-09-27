"""Create a focused FY 2025-26 review from the saved inter-location proposals."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, date
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.inter_location_payment_updates import plan_customer_payment_moves


SOURCE = Path("output/inter_location_payment_proposals.json")
DESTINATION = Path("output/inter_location_payment_proposals_fy2526.md")


def main() -> int:
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    if report.get("view_id") != "264324000008274019":
        raise ValueError("Unexpected proposal source")
    payments = [p for p in report["proposals"]
                if date(2025, 4, 1) <= datetime.strptime(p["date"], "%d/%m/%Y").date()
                <= date(2026, 3, 31)]
    payments.sort(key=lambda p: (p["date"], p["payment_id"]))
    counts = Counter(p["status"] for p in payments)
    batch_moves = plan_customer_payment_moves(
        get_books_client(), payments, prefix="SB2526CP-", limit=15,
        excluded_payment_ids=frozenset({"1094368000053835002"}))
    if len(batch_moves) != 15:
        raise ValueError(f"Expected 15 live Books-verified candidates; found {len(batch_moves)}")
    by_id = {p["payment_id"]: p for p in payments}
    proposed_numbers = {move["payment_id"]: move["new_number"] for move in batch_moves}
    lines = ["# FY 2025–26 inter-location payment proposals", "",
             f"Source: Zoho Analytics Query Table {report['view_id']}. "
             f"{len(payments)} payments: {counts['proposed']} proposed, "
             f"{counts['manual_review']} manual review.", "",
             "## Next 15 customer-payment candidates", "",
             "These destination numbers are planned from current Books data; they are not reserved.", "",
             "| Payment ID | Date | Amount | Bank | From | To | Invoice | Destination number |",
             "| --- | --- | ---: | --- | --- | --- | --- | --- |"]
    for move in batch_moves:
        p = by_id[move["payment_id"]]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in (
            p["payment_id"], p["date"], p["amount"], p["bank_account_name"],
            p["from_location"], p["to_location"], ", ".join(p["document_numbers"]),
            move["new_number"])) + " |")
    lines += ["", "## All FY 2025–26 payments", "",
              "| Status | Type | Payment ID | Date | Amount | Bank | From | To | Documents | Destination number | Reason |",
              "| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |"]
    for p in payments:
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in (
            p["status"], p["payment_type"], p["payment_id"], p["date"], p["amount"],
            p["bank_account_name"], p["from_location"], p["to_location"],
            ", ".join(p["document_numbers"]), proposed_numbers.get(p["payment_id"], "Pending"),
            p["reason"])) + " |")
    lines += ["", "No Books changes are made by this report.", ""]
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {DESTINATION}: {len(payments)} payments; {len(batch_moves)} numbered batch candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
