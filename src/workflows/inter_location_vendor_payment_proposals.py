"""Verify vendor-payment moves against Books and assign review-only numbers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, TypedDict

from workflows.core.payments import payment_series_params, payment_series_records, payment_number_suffix
from workflows.core.matching import parse_currency_amount as _amount


class VendorPaymentMove(TypedDict):
    payment_id: str
    date: str
    amount: str
    bank_account_id: str
    old_number: str
    destination_number: str
    from_location_id: str
    to_location_id: str
    bill_numbers: list[str]


def _last_suffix(books: Any, prefix: str) -> int:
    response = books.vendor_payments.list(payment_series_params(prefix))
    records = payment_series_records(
        response, prefix, response_keys=("vendorpayments", "vendor_payments"),
        error_message=f"Books did not confirm vendor series lookup: {prefix}",
    )
    if len(records) != 1:
        raise ValueError(f"No existing vendor payment found in {prefix}")
    number = str(records[0].get("payment_number") or "")
    return payment_number_suffix(
        number, prefix, error_message=f"Invalid highest vendor payment number: {number}")


def propose_vendor_payment_moves(
    books: Any, proposals: list[Mapping[str, Any]],
) -> tuple[list[VendorPaymentMove], list[dict[str, str]]]:
    """Preflight each FY25-26 vendor proposal and assign the next number per series."""
    candidates = sorted((p for p in proposals if p.get("status") == "proposed"
                         and p.get("payment_type") == "Vendor Payment"
                         and p.get("financial_year") == "FY 2025-26"),
                        key=lambda p: (datetime.strptime(p["date"], "%d/%m/%Y"), p["payment_id"]))
    prefixes = {str(p.get("expected_number_prefix") or "") for p in candidates}
    if "" in prefixes:
        raise ValueError("Proposed vendor payment lacks destination series")
    next_suffix = {prefix: _last_suffix(books, prefix) for prefix in sorted(prefixes)}
    moves: list[VendorPaymentMove] = []
    held: list[dict[str, str]] = []
    seen: set[str] = set()
    for proposal in candidates:
        payment_id = str(proposal["payment_id"])
        if payment_id in seen:
            raise ValueError(f"Duplicate vendor payment proposal: {payment_id}")
        seen.add(payment_id)
        try:
            date = datetime.strptime(proposal["date"], "%d/%m/%Y").date()
            if not (datetime(2025, 4, 1).date() <= date <= datetime(2026, 3, 31).date()):
                raise ValueError("Payment date is outside FY 2025-26")
            payment = books.vendor_payments.get(payment_id)["vendorpayment"]
            if str(payment.get("payment_id")) != payment_id:
                raise ValueError("Books returned a different payment")
            if str(payment.get("location_id")) == str(proposal["to_location_id"]):
                continue  # Analytics can still show a payment already moved in Books.
            if (str(payment.get("location_id")) != str(proposal["from_location_id"])
                    or str(payment.get("paid_through_account_id")) != str(proposal["bank_account_id"])
                    or str(payment.get("date")) != date.isoformat()
                    or _amount(payment.get("amount")) != _amount(proposal["amount"])):
                raise ValueError("Current Books payment differs from Analytics proposal")
            bills = payment.get("bills") or []
            if not bills:
                raise ValueError("No bill allocations in Books")
            numbers: set[str] = set()
            for allocation in bills:
                bill = books.bills.get(str(allocation["bill_id"]))["bill"]
                if str(bill.get("location_id")) != str(proposal["to_location_id"]):
                    raise ValueError("Allocated bill location differs")
                numbers.add(str(bill.get("bill_number") or ""))
            if numbers != set(proposal["document_numbers"]):
                raise ValueError("Allocated bill numbers differ")
            prefix = str(proposal["expected_number_prefix"])
            old_number = str(payment.get("payment_number") or "")
            if old_number.startswith(prefix) and old_number[len(prefix):].isdigit():
                continue  # This proposal lists payments requiring a number-series change.
            next_suffix[prefix] += 1
            destination_number = f"{prefix}{next_suffix[prefix]:05d}"
            moves.append({"payment_id": payment_id, "date": date.isoformat(),
                          "amount": str(_amount(payment["amount"])),
                          "bank_account_id": str(proposal["bank_account_id"]),
                          "old_number": old_number,
                          "destination_number": destination_number,
                          "from_location_id": str(proposal["from_location_id"]),
                          "to_location_id": str(proposal["to_location_id"]),
                          "bill_numbers": sorted(numbers)})
        except (KeyError, TypeError, ValueError) as exc:
            held.append({"payment_id": payment_id, "reason": str(exc)})
    return moves, held
