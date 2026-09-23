"""Update Books bills while preserving paid vendor payments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from zoho.books import ZohoBooksAPI


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class BillUpdateResult:
    bill_id: str
    old_total: Decimal
    new_total: Decimal
    unapplied_credit: Decimal
    payment_ids: tuple[str, ...]
    dry_run: bool


def _payment_payload(payment: Mapping[str, Any], bills: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "vendor_id", "date", "amount", "paid_through_account_id", "payment_mode",
        "reference_number", "description", "exchange_rate", "currency_id", "location_id",
    )
    payload = {field: payment[field] for field in fields if field in payment}
    payload["bills"] = bills
    return payload


def _allocations(payment: Mapping[str, Any], bill_id: str, target_amount: Decimal | None) -> list[dict[str, Any]]:
    result = []
    for entry in payment["bills"]:
        if str(entry["bill_id"]) == bill_id and target_amount is None:
            continue
        amount = target_amount if str(entry["bill_id"]) == bill_id else _money(entry["amount_applied"])
        result.append({
            "bill_id": str(entry["bill_id"]),
            "bill_payment_id": str(entry["bill_payment_id"]),
            "amount_applied": float(amount),
            "tax_amount_withheld": entry.get("tax_amount_withheld", 0),
        })
    return result


def update_bill_with_payment_reallocation(
    books: ZohoBooksAPI,
    bill_id: str,
    update_data: Mapping[str, Any],
    *,
    expected_total: Decimal,
    dry_run: bool = True,
) -> BillUpdateResult:
    """Update a bill; temporarily unapply payments when its total decreases.

    The payment amount and allocations to other bills remain unchanged. Excess
    becomes unapplied vendor payment credit. The caller must supply the expected
    new total, since Books alone calculates the final tax and rounding.
    """
    original = books.bills.get(bill_id)["bill"]
    old_total = _money(original["total"])
    expected_total = _money(expected_total)
    if expected_total < 0:
        raise ValueError("expected_total cannot be negative")
    payment_refs = original.get("payments", [])
    payments = []
    for reference in payment_refs:
        payment = books.vendor_payments.get(str(reference["payment_id"]))["vendorpayment"]
        if str(payment["vendor_id"]) != str(original["vendor_id"]):
            raise ValueError("Payment vendor does not match bill vendor")
        targets = [row for row in payment["bills"] if str(row["bill_id"]) == bill_id]
        if len(targets) != 1:
            raise ValueError("Expected one target allocation per vendor payment")
        payments.append((payment, _money(targets[0]["amount_applied"])))
    paid_total = sum((amount for _, amount in payments), Decimal("0.00"))
    credit = max(Decimal("0.00"), paid_total - expected_total)
    result = BillUpdateResult(
        bill_id, old_total, expected_total, credit,
        tuple(str(payment["payment_id"]) for payment, _ in payments), dry_run,
    )
    if dry_run:
        return result

    if expected_total >= old_total or not payments:
        books.bills.update(bill_id, dict(update_data))
    else:
        detached = []
        try:
            for payment, _ in payments:
                books.vendor_payments.update(
                    str(payment["payment_id"]),
                    _payment_payload(payment, _allocations(payment, bill_id, Decimal("0.00"))),
                )
                detached.append(payment)
                checked = books.vendor_payments.get(str(payment["payment_id"]))["vendorpayment"]
                checked_applied = sum(
                    (_money(row["amount_applied"]) for row in checked["bills"]
                     if str(row["bill_id"]) == bill_id), Decimal("0.00")
                )
                if checked_applied:
                    raise RuntimeError("Vendor payment remained applied to the bill")
            books.bills.update(bill_id, dict(update_data))
        except Exception:
            for payment in reversed(detached):
                books.vendor_payments.update(
                    str(payment["payment_id"]),
                    _payment_payload(payment, _allocations(payment, bill_id, _money(next(
                        row["amount_applied"] for row in payment["bills"] if str(row["bill_id"]) == bill_id
                    )))),
                )
            raise

        updated_bill = books.bills.get(bill_id)["bill"]
        remaining = _money(updated_bill["total"])
        for payment, amount in payments:
            applied = min(amount, remaining)
            current = books.vendor_payments.get(str(payment["payment_id"]))["vendorpayment"]
            rows = _allocations(current, bill_id, None)
            if applied:
                rows.append({"bill_id": bill_id, "amount_applied": float(applied)})
            books.vendor_payments.update(
                str(payment["payment_id"]), _payment_payload(current, rows),
            )
            remaining -= applied

    refreshed = books.bills.get(bill_id)["bill"]
    actual_total = _money(refreshed["total"])
    if actual_total != expected_total:
        raise RuntimeError(f"Bill total is {actual_total}, expected {expected_total}")
    return BillUpdateResult(bill_id, old_total, actual_total, credit,
                            result.payment_ids, False)
