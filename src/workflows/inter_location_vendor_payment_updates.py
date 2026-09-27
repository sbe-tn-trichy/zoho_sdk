"""Apply explicitly reviewed vendor-payment moves with numbered read-back."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from workflows.inter_location_vendor_payment_proposals import VendorPaymentMove


def _amount(value: Any) -> Decimal:
    return Decimal(str(value).replace("INR", "").replace(",", "").strip())


def preflight_vendor_moves(books: Any, moves: list[VendorPaymentMove]) -> None:
    """Recheck selected payments, bills, and destination number availability."""
    if not moves or len({m["payment_id"] for m in moves}) != len(moves):
        raise ValueError("A nonempty batch with unique payment IDs is required")
    prefixes = {m["destination_number"].split("-")[0] + "-" for m in moves}
    if len(prefixes) != 1:
        raise ValueError("Selected vendor payments must use one destination series")
    prefix = next(iter(prefixes))
    response = books.vendor_payments.list({"payment_number_startswith": prefix,
        "sort_column": "payment_number", "sort_order": "D", "page": 1, "per_page": 1})
    context = response.get("page_context") or {}
    if (context.get("sort_column") != "payment_number" or context.get("sort_order") != "D"
            or not any(c.get("column_name") == "payment_number" and c.get("search_text") == prefix
                       and c.get("comparator") == "startswith" for c in context.get("search_criteria") or [])):
        raise ValueError("Books did not confirm vendor series filter and descending sort")
    records = response.get("vendorpayments", response.get("vendor_payments", []))
    if len(records) != 1:
        raise ValueError("Destination vendor series has no highest number")
    highest = str(records[0].get("payment_number") or "")
    if not highest.startswith(prefix) or not highest[len(prefix):].isdigit():
        raise ValueError("Destination vendor series maximum is malformed")
    suffixes = [int(move["destination_number"][len(prefix):]) for move in moves]
    if len(set(suffixes)) != len(suffixes) or min(suffixes) <= int(highest[len(prefix):]):
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
    response = books.vendor_payments.list({"payment_number_startswith": prefix,
        "sort_column": "payment_number", "sort_order": "D", "page": 1,
        "per_page": len(moves) + max(int(m["destination_number"][len(prefix):]) for m in moves)
                     - min(int(m["destination_number"][len(prefix):]) for m in moves)})
    context = response.get("page_context") or {}
    if (context.get("sort_column") != "payment_number" or context.get("sort_order") != "D"
            or not any(c.get("column_name") == "payment_number" and c.get("search_text") == prefix
                       and c.get("comparator") == "startswith" for c in context.get("search_criteria") or [])):
        raise ValueError("Books did not confirm vendor batch read-back filter and sort")
    records = response.get("vendorpayments", response.get("vendor_payments", []))
    by_id = {str(record.get("payment_id")): record for record in records}
    results: list[dict[str, str]] = []
    for move in moves:
        saved = by_id.get(move["payment_id"])
        if (saved is None or str(saved.get("payment_number")) != move["destination_number"]
                or str(saved.get("location_id")) != move["to_location_id"]
                or str(saved.get("paid_through_account_id")) != move["bank_account_id"]
                or str(saved.get("date")) != move["date"]
                or _amount(saved.get("amount")) != _amount(move["amount"])):
            raise ValueError(f"Vendor batch read-back mismatch: {move['payment_id']}")
        results.append({"payment_id": move["payment_id"],
                        "payment_number": move["destination_number"], "status": "verified"})
    return results
