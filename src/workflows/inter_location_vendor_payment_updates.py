"""Apply explicitly reviewed vendor-payment moves with numbered read-back."""

from __future__ import annotations

from typing import Any

from workflows.inter_location_vendor_payment_proposals import VendorPaymentMove

from workflows.core.payments import (
    PaymentState, payment_state_matches, payment_series_params, payment_series_records, payment_number_suffix,
)
from workflows.core.matching import parse_currency_amount as _amount


def preflight_vendor_moves(books: Any, moves: list[VendorPaymentMove]) -> None:
    """Recheck selected payments, bills, and destination number availability."""
    if not moves or len({m["payment_id"] for m in moves}) != len(moves):
        raise ValueError("A nonempty batch with unique payment IDs is required")
    prefixes = {m["destination_number"].split("-")[0] + "-" for m in moves}
    if len(prefixes) != 1:
        raise ValueError("Selected vendor payments must use one destination series")
    prefix = next(iter(prefixes))
    response = books.vendor_payments.list(payment_series_params(prefix))
    records = payment_series_records(
        response, prefix, response_keys=("vendorpayments", "vendor_payments"),
        error_message="Books did not confirm vendor series filter and descending sort",
    )
    if len(records) != 1:
        raise ValueError("Destination vendor series has no highest number")
    highest = str(records[0].get("payment_number") or "")
    highest_suffix = payment_number_suffix(
        highest, prefix, error_message="Destination vendor series maximum is malformed")
    suffixes = [int(move["destination_number"][len(prefix):]) for move in moves]
    if len(set(suffixes)) != len(suffixes) or min(suffixes) <= highest_suffix:
        raise ValueError(f"Proposed vendor numbers collide with or precede Books maximum {highest}")
    for move in moves:
        payment = books.vendor_payments.get(move["payment_id"])["vendorpayment"]
        if (str(payment.get("payment_id")) != move["payment_id"]
                or str(payment.get("payment_number")) != move["old_number"]
                or str(payment.get("location_id")) != move["from_location_id"]
                or str(payment.get("paid_through_account_id")) != move["bank_account_id"]
                or str(payment.get("date")) != move["date"]
                or _amount(payment.get("amount")) != _amount(move["amount"])):
            raise ValueError(f"Vendor payment changed in Books: {move['payment_id']}")
        allocations = payment.get("bills") or []
        if not allocations:
            raise ValueError(f"Vendor payment has no bill allocations: {move['payment_id']}")
        numbers = set()
        for allocation in allocations:
            bill = books.bills.get(str(allocation["bill_id"]))["bill"]
            if str(bill.get("location_id")) != move["to_location_id"]:
                raise ValueError(f"Allocated bill location changed: {move['payment_id']}")
            numbers.add(str(bill.get("bill_number") or ""))
        if numbers != set(move["bill_numbers"]):
            raise ValueError(f"Allocated bills changed: {move['payment_id']}")


def submit_vendor_move(books: Any, move: VendorPaymentMove) -> None:
    """Send one multipart location and number update."""
    number = move["destination_number"]
    prefix, suffix = number.rsplit("-", 1)
    response = books.vendor_payments.update_with_number_series(move["payment_id"], {
        "location_id": move["to_location_id"], "payment_number_prefix": prefix + "-",
        "payment_number_suffix": suffix})
    if response.get("code") != 0:
        raise ValueError(f"Books rejected vendor payment {move['payment_id']}: {response.get('message')}")


def verify_vendor_batch(books: Any, moves: list[VendorPaymentMove]) -> list[dict[str, str]]:
    """Read one descending series page and check every saved vendor payment."""
    if not moves:
        raise ValueError("Cannot verify an empty vendor batch")
    prefix = moves[0]["destination_number"].rsplit("-", 1)[0] + "-"
    page_size = len(moves) + max(int(m["destination_number"][len(prefix):]) for m in moves) - min(int(m["destination_number"][len(prefix):]) for m in moves)
    response = books.vendor_payments.list(payment_series_params(prefix, per_page=page_size))
    records = payment_series_records(
        response, prefix, response_keys=("vendorpayments", "vendor_payments"),
        error_message="Books did not confirm vendor batch read-back filter and sort",
    )
    by_id = {str(record.get("payment_id")): record for record in records}
    results: list[dict[str, str]] = []
    for move in moves:
        saved = by_id.get(move["payment_id"])
        expected = PaymentState(move["to_location_id"], move["destination_number"],
                                move["bank_account_id"], move["date"], move["amount"])
        if not payment_state_matches(saved, expected, bank_account_key="paid_through_account_id"):
            raise ValueError(f"Vendor batch read-back mismatch: {move['payment_id']}")
        results.append({"payment_id": move["payment_id"],
                        "payment_number": move["destination_number"], "status": "verified"})
    return results
