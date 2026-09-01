from datetime import date
from decimal import Decimal

from apps.backfill_online_payment_creator_fields import find_books_payment


def _values(**overrides):
    values = {
        "date": date(2026, 8, 29),
        "amount": Decimal("500"),
        "reference": "UTR-100",
        "customer_id": "customer-1",
        "books_payment_id": "",
        "books_payment_number": "",
    }
    values.update(overrides)
    return values


def _payment(**overrides):
    payment = {
        "payment_id": "payment-1",
        "payment_number": "PAY-1",
        "date": "2026-08-29",
        "amount": 500,
        "reference_number": "UTR-100",
        "customer_id": "customer-1",
    }
    payment.update(overrides)
    return payment


def test_exact_customer_date_amount_reference_match():
    payment = _payment()

    resolved, source = find_books_payment(_values(), [payment])

    assert resolved is payment
    assert source == "exact_customer_date_amount_reference"


def test_ambiguous_match_is_not_selected():
    payments = [_payment(payment_id="one"), _payment(payment_id="two")]

    resolved, source = find_books_payment(_values(), payments)

    assert resolved is None
    assert source == "payment_ambiguous"


def test_customer_id_must_match():
    resolved, source = find_books_payment(
        _values(),
        [_payment(customer_id="different-customer")],
    )

    assert resolved is None
    assert source == "payment_missing"
