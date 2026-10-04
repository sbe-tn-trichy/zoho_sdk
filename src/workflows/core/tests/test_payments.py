from datetime import date
from decimal import Decimal, InvalidOperation

import pytest

from workflows.core import (
    PaymentEvidence, PaymentState, build_payment_indexes, parse_currency_amount, payment_evidence_matches,
    payment_state_matches,
    payment_number_suffix, payment_series_params, payment_series_records, references_intersect,
)
from workflows.core.matching import normalize_payment_reference


def series_response():
    return {"vendorpayments": [{"payment_number": "VP-0009"}], "page_context": {
        "sort_column": "payment_number", "sort_order": "D", "search_criteria": [
            {"column_name": "payment_number", "search_text": "VP-", "comparator": "startswith"}]}}


def test_series_aliases_and_suffix_preserve_number_padding():
    response = series_response()
    response["vendor_payments"] = response.pop("vendorpayments")
    records = payment_series_records(response, "VP-", response_keys=("vendorpayments", "vendor_payments"),
                                     error_message="unconfirmed series")
    assert payment_number_suffix(records[0]["payment_number"], "VP-", error_message="bad number") == 9
    assert payment_series_params("VP-", per_page=3) == {
        "payment_number_startswith": "VP-", "sort_column": "payment_number",
        "sort_order": "D", "page": 1, "per_page": 3}


@pytest.mark.parametrize("field, value", [("sort_column", "date"), ("sort_order", "A"), ("search_criteria", [])])
def test_series_rejects_unconfirmed_filter_or_sort(field, value):
    response = series_response()
    response["page_context"][field] = value
    with pytest.raises(ValueError, match="unconfirmed series"):
        payment_series_records(response, "VP-", response_keys=("vendorpayments",), error_message="unconfirmed series")


def test_series_rejects_wrong_prefix_and_invalid_records():
    response = series_response()
    with pytest.raises(ValueError, match="unconfirmed"):
        payment_series_records(response, "CP-", response_keys=("vendorpayments",), error_message="unconfirmed")
    response["vendorpayments"] = {}
    with pytest.raises(ValueError, match="invalid payment series page"):
        payment_series_records(response, "VP-", response_keys=("vendorpayments",), error_message="unconfirmed")


@pytest.mark.parametrize("number", ["VP-", "VP-text", "CP-9", "VP--9"])
def test_number_suffix_rejects_unexpected_series_or_non_numeric_suffix(number):
    with pytest.raises(ValueError, match="bad number"):
        payment_number_suffix(number, "VP-", error_message="bad number")


def test_indexes_preserve_number_ambiguity_and_id_aliases():
    payments = [{"payment_id": "1", "payment_number": "CP-1"},
                {"id": "2", "payment_number": "cp 1"}]
    by_id, by_number = build_payment_indexes(payments)
    assert by_id == {"1": payments[0], "2": payments[1]}
    assert by_number["cp1"] == payments
    assert build_payment_indexes(payments, id_keys=("payment_id",))[0] == {"1": payments[0]}


def test_evidence_uses_explicit_customer_policy_and_absolute_amount():
    payment = {"date": "2026-10-04", "amount": "-1,000", "reference_number": "UTR-1",
               "customer_name": "Acme & Co", "customer_id": "c1"}
    by_name = PaymentEvidence(date(2026, 10, 4), Decimal("1000"), "utr1", "acmeco")
    by_id = PaymentEvidence(date(2026, 10, 4), Decimal("1000"), "utr1", "c1")
    assert payment_evidence_matches(payment, by_name, customer_key="customer_name",
                                    normalize_customer=normalize_payment_reference)
    assert payment_evidence_matches(payment, by_id, customer_key="customer_id")
    assert not payment_evidence_matches(payment, by_name, customer_key="customer_id")


@pytest.mark.parametrize("field, value", [("date", "invalid"), ("amount", "invalid"),
                                         ("reference_number", "other"), ("customer_id", "other")])
def test_evidence_rejects_mismatched_or_invalid_financial_fields(field, value):
    payment = {"date": "2026-10-04", "amount": "100", "reference_number": "R", "customer_id": "c"}
    payment[field] = value
    evidence = PaymentEvidence(date(2026, 10, 4), Decimal("100"), "r", "c")
    assert not payment_evidence_matches(payment, evidence, customer_key="customer_id")


def test_currency_parser_and_reference_comparison_retain_strict_semantics():
    assert parse_currency_amount(" INR -1,200.50 ") == Decimal("-1200.50")
    with pytest.raises(InvalidOperation):
        parse_currency_amount("missing")
    assert references_intersect((None, " ABC-1 "), ("abc-1", ""))
    assert not references_intersect((None, ""), (None, ""))
    assert not references_intersect(("ABC-1",), ("ABC1",))


@pytest.mark.parametrize("bank_key", ["account_id", "paid_through_account_id"])
def test_payment_readback_verifies_all_fields_and_preserves_strict_amount_errors(bank_key):
    state = PaymentState("loc", "P-1", "bank", "2026-10-04", "1000")
    record = {"location_id": "loc", "payment_number": "P-1", bank_key: "bank",
              "date": "2026-10-04", "amount": "INR 1,000"}
    assert payment_state_matches(record, state, bank_account_key=bank_key)
    assert not payment_state_matches(None, state, bank_account_key=bank_key)
    for key in ("location_id", "payment_number", bank_key, "date", "amount"):
        assert not payment_state_matches({**record, key: "2"}, state, bank_account_key=bank_key)
    with pytest.raises(InvalidOperation):
        payment_state_matches({**record, "amount": "invalid"}, state, bank_account_key=bank_key)
