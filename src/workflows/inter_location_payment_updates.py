"""Preflight and apply a reviewed customer-payment location and number batch."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, TypedDict

from workflows.core.payments import (
    PaymentState, payment_state_matches, payment_series_params, payment_series_records, payment_number_suffix,
)
from workflows.core.matching import parse_currency_amount as _amount


class PaymentMove(TypedDict):
    payment_id: str
    source_location_id: str
    target_location_id: str
    bank_account_id: str
    date: str
    amount: str
    old_number: str
    new_number: str
    prefix: str
    suffix: str


def plan_customer_payment_moves(
    books: Any, proposals: list[Mapping[str, Any]], *, prefix: str,
    last_suffix: int | None = None, limit: int | None = None,
    excluded_payment_ids: frozenset[str] = frozenset(),
) -> list[PaymentMove]:
    """Verify all source payments, invoices, and available numbers before mutation."""
    if not prefix or (last_suffix is not None and last_suffix < 0) or (limit is not None and limit <= 0):
        raise ValueError("A valid prefix, last suffix, and positive limit are required")
    selected = sorted((p for p in proposals if p.get("status") == "proposed"
                       and p.get("payment_type") == "Customer Payment"
                       and p.get("expected_number_prefix") == prefix
                       and str(p.get("payment_id")) not in excluded_payment_ids),
                      key=lambda p: (datetime.strptime(p["date"], "%d/%m/%Y"), p["payment_id"]))
    page = books.customer_payments.list(payment_series_params(prefix))
    records = payment_series_records(
        page, prefix, response_keys=("customer_payments", "customerpayments"),
        error_message="Books did not confirm the requested series filter and descending sort",
    )
    if len(records) != 1:
        raise ValueError(f"No existing Books number found for {prefix}")
    highest_number = str(records[0].get("payment_number") or "")
    highest_suffix = payment_number_suffix(
        highest_number, prefix, error_message=f"Unexpected highest Books payment number: {highest_number}")
    if last_suffix is None:
        last_suffix = highest_suffix
    elif last_suffix < highest_suffix:
        raise ValueError(f"Last suffix is stale; Books already has {highest_number}")
    moves: list[PaymentMove] = []
    seen: set[str] = set()
    for proposal in selected:
        if limit is not None and len(moves) >= limit:
            break
        payment_id = str(proposal["payment_id"])
        if payment_id in seen:
            raise ValueError(f"Duplicate proposal: {payment_id}")
        seen.add(payment_id)
        payment = books.customer_payments.get(payment_id)["payment"]
        date = datetime.strptime(proposal["date"], "%d/%m/%Y").strftime("%Y-%m-%d")
        if str(payment.get("payment_id")) != payment_id:
            raise ValueError(f"Books returned a different payment: {payment_id}")
        if str(payment.get("location_id")) != str(proposal["from_location_id"]):
            continue  # Analytics can lag a payment already moved in Books.
        if (str(payment.get("location_id")) != str(proposal["from_location_id"])
                or str(payment.get("account_id")) != str(proposal["bank_account_id"])
                or str(payment.get("date")) != date
                or _amount(payment.get("amount")) != _amount(proposal["amount"])):
            raise ValueError(f"Current Books payment differs from proposal: {payment_id}")
        allocations = payment.get("invoices") or []
        if not allocations:
            raise ValueError(f"No invoice allocations: {payment_id}")
        numbers = set()
        for allocation in allocations:
            invoice = books.invoices.get(str(allocation["invoice_id"]))["invoice"]
            if str(invoice.get("location_id")) != str(proposal["to_location_id"]):
                raise ValueError(f"Invoice location differs: {payment_id}")
            numbers.add(str(invoice.get("invoice_number")))
        if numbers != set(proposal["document_numbers"]):
            raise ValueError(f"Invoice allocations differ: {payment_id}")
        suffix = f"{last_suffix + len(moves) + 1:05d}"
        new_number = prefix + suffix
        moves.append({"payment_id": payment_id,
                      "source_location_id": str(proposal["from_location_id"]),
                      "target_location_id": str(proposal["to_location_id"]),
                      "bank_account_id": str(proposal["bank_account_id"]),
                      "date": date, "amount": str(_amount(proposal["amount"])),
                      "old_number": str(payment.get("payment_number") or ""),
                      "new_number": new_number, "prefix": prefix, "suffix": suffix})
    return moves


def apply_customer_payment_move(books: Any, move: PaymentMove) -> dict[str, str]:
    """Update one payment and require an exact read-back before continuing."""
    submit_customer_payment_move(books, move)
    payment_id = move["payment_id"]
    after = books.customer_payments.get(payment_id)["payment"]
    expected = PaymentState(move["target_location_id"], move["new_number"],
                            move["bank_account_id"], move["date"], move["amount"])
    if not payment_state_matches(after, expected, bank_account_key="account_id"):
        raise ValueError(f"Post-update verification failed for {payment_id}; inspect Books before retrying")
    return {"payment_id": payment_id, "payment_number": move["new_number"],
            "location_id": move["target_location_id"], "status": "verified"}


def submit_customer_payment_move(books: Any, move: PaymentMove) -> None:
    """Recheck source identity and submit exactly one multipart update."""
    payment_id = move["payment_id"]
    before = books.customer_payments.get(payment_id)["payment"]
    if (str(before.get("location_id")) != move["source_location_id"]
            or str(before.get("payment_number") or "") != move["old_number"]):
        raise ValueError(f"Payment changed after preflight: {payment_id}")
    response = books.customer_payments.update_with_number_series(payment_id, {
        "location_id": move["target_location_id"],
        "payment_number_prefix": move["prefix"],
        "payment_number_suffix": move["suffix"],
    })
    if response.get("code") != 0:
        raise ValueError(f"Books rejected location/number update for {payment_id}: {response.get('message')}")


def verify_customer_payment_batch(books: Any, moves: list[PaymentMove]) -> list[dict[str, str]]:
    """Read the destination series once and verify every applied batch payment."""
    if not moves or len(moves) > 200:
        raise ValueError("Batch verification requires 1 to 200 payments")
    prefixes = {move["prefix"] for move in moves}
    if len(prefixes) != 1:
        raise ValueError("Batch payments must use one number series")
    prefix = next(iter(prefixes))
    page = books.customer_payments.list(payment_series_params(prefix, per_page=len(moves)))
    records = payment_series_records(
        page, prefix, response_keys=("customer_payments", "customerpayments"),
        error_message="Books did not confirm the batch read-back filter and sort",
    )
    by_id = {str(record.get("payment_id")): record for record in records}
    if len(by_id) != len(moves):
        raise ValueError("Batch read-back did not return all updated payments")
    results: list[dict[str, str]] = []
    for move in moves:
        record = by_id.get(move["payment_id"])
        expected = PaymentState(move["target_location_id"], move["new_number"],
                                move["bank_account_id"], move["date"], move["amount"])
        if not payment_state_matches(record, expected, bank_account_key="account_id"):
            raise ValueError(f"Batch read-back mismatch for {move['payment_id']}")
        results.append({"payment_id": move["payment_id"], "payment_number": move["new_number"],
                        "location_id": move["target_location_id"], "status": "verified"})
    return results
