"""Pure payment identity and validated number-series helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from .matching import normalize_payment_reference, parse_currency_amount, parse_date, to_decimal, to_text


@dataclass(frozen=True)
class PaymentEvidence:
    date: date | None
    amount: Decimal | None
    reference: str
    customer: str


@dataclass(frozen=True)
class PaymentState:
    """Financial and numbering fields expected after a reviewed payment move."""

    location_id: str
    number: str
    bank_account_id: str
    date: str
    amount: str


def payment_state_matches(
    payment: Mapping[str, Any] | None, expected: PaymentState, *, bank_account_key: str,
) -> bool:
    """Verify read-back without hiding missing records or invalid amount failures."""
    return (
        payment is not None
        and str(payment.get("location_id")) == expected.location_id
        and str(payment.get("payment_number")) == expected.number
        and str(payment.get(bank_account_key)) == expected.bank_account_id
        and str(payment.get("date")) == expected.date
        and parse_currency_amount(payment.get("amount")) == parse_currency_amount(expected.amount)
    )


def payment_evidence_matches(
    payment: Mapping[str, Any], evidence: PaymentEvidence, *,
    customer_key: str, normalize_customer: Callable[[Any], str] = to_text,
) -> bool:
    """Compare date, absolute amount, reference and explicit customer evidence."""
    amount = to_decimal(payment.get("amount"))
    return (
        parse_date(payment.get("date")) == evidence.date
        and amount is not None and evidence.amount is not None
        and abs(amount) == abs(evidence.amount)
        and normalize_payment_reference(payment.get("reference_number")) == evidence.reference
        and normalize_customer(payment.get(customer_key)) == evidence.customer
    )


def build_payment_indexes(
    payments: Sequence[Mapping[str, Any]], *, id_keys: tuple[str, ...] = ("payment_id", "id"),
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    """Index native identifiers and normalized numbers without discarding ambiguity."""
    by_id: dict[str, Mapping[str, Any]] = {}
    by_number: dict[str, list[Mapping[str, Any]]] = {}
    for payment in payments:
        payment_id = next((to_text(payment.get(key)) for key in id_keys if payment.get(key)), "")
        number = normalize_payment_reference(payment.get("payment_number"))
        if payment_id:
            by_id[payment_id] = payment
        if number:
            by_number.setdefault(number, []).append(payment)
    return by_id, by_number


def payment_series_params(prefix: str, *, per_page: int = 1) -> dict[str, Any]:
    """Build the established descending first-page lookup for a payment series."""
    return {"payment_number_startswith": prefix, "sort_column": "payment_number",
            "sort_order": "D", "page": 1, "per_page": per_page}


def payment_series_records(
    response: Mapping[str, Any], prefix: str, *, response_keys: tuple[str, ...],
    error_message: str,
) -> list[Mapping[str, Any]]:
    """Reject responses that do not confirm the requested filter and sort."""
    context = response.get("page_context") or {}
    criteria = context.get("search_criteria") or []
    if (context.get("sort_column") != "payment_number" or context.get("sort_order") != "D"
            or not any(item.get("column_name") == "payment_number"
                       and item.get("search_text") == prefix
                       and item.get("comparator") == "startswith" for item in criteria)):
        raise ValueError(error_message)
    for key in response_keys:
        if key in response:
            records = response[key]
            if not isinstance(records, list):
                raise ValueError("Books returned an invalid payment series page")
            return records
    return []


def payment_number_suffix(number: str, prefix: str, *, error_message: str) -> int:
    if not number.startswith(prefix) or not number[len(prefix):].isdigit():
        raise ValueError(error_message)
    return int(number[len(prefix):])
