"""Verify and apply reviewed customer payment location changes in Books."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from workflows.inter_location_location_proposals import LocationProposal


ACCOUNT_ID = "1094368000002033114"


def _amount(value: Any) -> Decimal:
    return Decimal(str(value).replace("INR", "").replace(",", "").strip())


def _date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")


def verify_proposed_pair(books: Any, proposal: LocationProposal) -> dict[str, str]:
    """Check a proposal against current payment, invoice, vendor, and bill records."""
    if proposal["status"] != "proposed" or proposal["matching_evidence"] != "Exact reference":
        raise ValueError("Only exact-reference proposals can be applied")
    moves = proposal["moves"]
    if len(moves) != 1 or moves[0]["transaction_type"] != "customer_payment":
        raise ValueError("Expected exactly one customer payment move")
    move = moves[0]
    payment_id, vendor_id = proposal["customer_payment_id"], proposal["contra_id"]
    if move["transaction_id"] != payment_id or proposal["contra_type"] != "Vendor Payment":
        raise ValueError("Proposal transaction IDs/types disagree")
    payment = books.customer_payments.get(payment_id)["payment"]
    vendor = books.vendor_payments.get(vendor_id)["vendorpayment"]
    target = move["to_location_id"]
    source = move["from_location_id"]
    if str(payment.get("payment_id")) != payment_id or str(vendor.get("payment_id")) != vendor_id:
        raise ValueError(f"Books returned a different payment for {payment_id}")
    if str(payment.get("account_id")) != ACCOUNT_ID or str(vendor.get("paid_through_account_id")) != ACCOUNT_ID:
        raise ValueError(f"Clearing account changed for {payment_id}")
    if str(payment.get("location_id")) not in (source, target) or str(vendor.get("location_id")) != target:
        raise ValueError(f"Payment locations changed for {payment_id}")
    if (payment.get("date") != vendor.get("date") or payment.get("date") != _date(proposal["date"])
            or _amount(payment.get("amount")) != _amount(vendor.get("amount"))
            or _amount(payment.get("amount")) != _amount(proposal["amount"])):
        raise ValueError(f"Date or amount changed for {payment_id}")
    reference = str(payment.get("reference_number") or "")
    if not reference or reference != str(vendor.get("reference_number") or ""):
        raise ValueError(f"Reference no longer matches for {payment_id}")

    invoices = payment.get("invoices") or []
    bills = vendor.get("bills") or []
    if not invoices or not bills:
        raise ValueError(f"Missing allocations for {payment_id}")
    current_invoice_numbers: set[str] = set()
    for allocation in invoices:
        invoice = books.invoices.get(str(allocation["invoice_id"]))["invoice"]
        if str(invoice.get("location_id")) != target:
            raise ValueError(f"Invoice location changed for {payment_id}")
        current_invoice_numbers.add(str(invoice.get("invoice_number")))
    current_bill_numbers: set[str] = set()
    for allocation in bills:
        bill = books.bills.get(str(allocation["bill_id"]))["bill"]
        if str(bill.get("location_id")) != target:
            raise ValueError(f"Bill location changed for {payment_id}")
        current_bill_numbers.add(str(bill.get("bill_number")))
    if current_invoice_numbers != set(proposal["invoice_numbers"]) or current_bill_numbers != set(proposal["bill_numbers"]):
        raise ValueError(f"Allocated documents changed for {payment_id}")
    return {"payment_id": payment_id, "vendor_id": vendor_id, "from_location_id": source,
            "to_location_id": target, "current_location_id": str(payment["location_id"]),
            "date": str(payment["date"]), "amount": str(payment["amount"]), "reference": reference}


def apply_verified_move(books: Any, verified: Mapping[str, str]) -> dict[str, str]:
    """Move one customer payment and immediately verify both paired locations."""
    payment_id = verified["payment_id"]
    target = verified["to_location_id"]
    current = books.customer_payments.get(payment_id)["payment"]
    if str(current.get("location_id")) != verified["current_location_id"]:
        raise ValueError(f"Payment location changed after preflight for {payment_id}")
    if str(current.get("location_id")) != target:
        response = books.customer_payments.update(payment_id, {"location_id": target})
        if response.get("code") != 0:
            raise ValueError(f"Books rejected location update for {payment_id}: {response.get('message')}")
        status = "moved"
    else:
        status = "already_at_target"
    payment = books.customer_payments.get(payment_id)["payment"]
    vendor = books.vendor_payments.get(verified["vendor_id"])["vendorpayment"]
    if (str(payment.get("location_id")) != target or str(vendor.get("location_id")) != target
            or str(payment.get("account_id")) != ACCOUNT_ID
            or str(vendor.get("paid_through_account_id")) != ACCOUNT_ID
            or str(payment.get("reference_number")) != verified["reference"]
            or str(vendor.get("reference_number")) != verified["reference"]
            or str(payment.get("date")) != verified["date"]
            or str(vendor.get("date")) != verified["date"]
            or _amount(payment.get("amount")) != _amount(verified["amount"])
            or _amount(vendor.get("amount")) != _amount(verified["amount"])):
        raise ValueError(f"Post-update verification failed for {payment_id}")
    return {"payment_id": payment_id, "vendor_id": verified["vendor_id"],
            "location_id": target, "status": status}
