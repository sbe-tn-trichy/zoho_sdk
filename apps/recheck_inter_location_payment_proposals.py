"""Recheck every FY 2025-26 payment proposal against current Zoho Books."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client


SOURCE = Path("output/inter_location_payment_proposals.json")
MARKDOWN = Path("output/inter_location_payment_proposals.md")
AUDIT = Path("output/inter_location_payment_proposals_books_recheck.json")


def _amount(value: object) -> Decimal:
    return Decimal(str(value).replace("INR", "").replace(",", "").strip())


def recheck(books: object, proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return outstanding proposals and a Books observation for each source row."""
    remaining: list[dict] = []
    audit: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for proposal in proposals:
        kind = proposal["payment_type"]
        payment_id = str(proposal["payment_id"])
        key = (kind, payment_id)
        if key in seen:
            raise ValueError(f"Duplicate payment proposal: {kind} {payment_id}")
        seen.add(key)
        if kind == "Customer Payment":
            payload = books.customer_payments.get(payment_id)["payment"]
            account_key = "account_id"
            expected_date = datetime.strptime(proposal["date"], "%d/%m/%Y").date().isoformat()
        elif kind == "Vendor Payment":
            payload = books.vendor_payments.get(payment_id)["vendorpayment"]
            account_key = "paid_through_account_id"
            expected_date = datetime.strptime(proposal["date"], "%d/%m/%Y").date().isoformat()
        else:
            raise ValueError(f"Unsupported payment type: {kind}")
        if str(payload.get("payment_id")) != payment_id:
            raise ValueError(f"Books returned a different payment for {kind} {payment_id}")
        current_location = str(payload.get("location_id") or "")
        source_location = str(proposal.get("from_location_id") or "")
        target_location = str(proposal.get("to_location_id") or "")
        identity_matches = (
            str(payload.get(account_key) or "") == str(proposal.get("bank_account_id") or "")
            and str(payload.get("date") or "") == expected_date
            and _amount(payload.get("amount")) == _amount(proposal["amount"])
        )
        if not identity_matches:
            state = "changed_details"
        elif target_location and current_location == target_location:
            state = "already_updated"
        elif (current_location == source_location and
              proposal.get("expected_number_prefix") and
              str(payload.get("payment_number") or "").startswith(
                  str(proposal["expected_number_prefix"]))):
            state = "destination_number_source_location"
        elif current_location == source_location:
            state = "outstanding"
        else:
            state = "changed_location_review"
        audit.append({"payment_type": kind, "payment_id": payment_id,
                      "state": state, "current_location_id": current_location,
                      "source_location_id": source_location,
                      "target_location_id": target_location,
                      "current_number": str(payload.get("payment_number") or "")})
        if state != "already_updated":
            if state != "outstanding":
                proposal = dict(proposal)
                proposal["status"] = "manual_review"
                proposal["reason"] = f"Books recheck: {state}; inspect current payment"
            remaining.append(proposal)
    return remaining, audit


def main() -> int:
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    if (report.get("view_id"), report.get("financial_year")) != (
        "264324000008274019", "FY 2025-26"
    ):
        raise ValueError("Unexpected proposal source or financial year")
    source = report["proposals"]
    remaining, observations = recheck(get_books_client(), source)
    counts = Counter(p["status"] for p in remaining)
    states = Counter(item["state"] for item in observations)
    report["proposals"] = remaining
    report["payment_count"] = len(remaining)
    report["status_counts"] = dict(counts)
    report["books_rechecked_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["already_updated_removed"] = states["already_updated"]
    audit = {"view_id": report["view_id"], "financial_year": report["financial_year"],
             "checked_count": len(observations), "state_counts": dict(states),
             "observations": observations}
    lines = ["# FY 2025–26 inter-location payment location proposals", "",
             f"Source: Analytics Query Table {report['view_id']}. Books checked: {len(observations)}; "
             f"already updated and removed: {states['already_updated']}; remaining: {len(remaining)}.", "",
             "Verify current Books payment, document, and destination number-series state before applying a move.", "",
             "| Status | Bank account | Payment type | Payment ID | Date | Amount | From | To | Number prefix | Documents | Reason |",
             "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |"]
    for proposal in remaining:
        values = (proposal["status"], proposal["bank_account_name"], proposal["payment_type"],
                  proposal["payment_id"], proposal["date"], proposal["amount"],
                  proposal["from_location"], proposal["to_location"],
                  proposal["expected_number_prefix"], ", ".join(proposal["document_numbers"]),
                  proposal["reason"])
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines.extend(["", "No Zoho Books locations were changed by this recheck.", ""])
    AUDIT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    SOURCE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MARKDOWN.write_text("\n".join(lines), encoding="utf-8")
    print(f"Checked {len(observations)}: removed {states['already_updated']} already updated; "
          f"{len(remaining)} remain ({counts['proposed']} proposed, {counts['manual_review']} manual review).")
    print(f"Reports: {MARKDOWN}, {SOURCE}; audit: {AUDIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
