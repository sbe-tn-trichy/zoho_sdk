from decimal import Decimal

import pytest

from workflows.gstr2_verification import total_mismatch


def test_signed_portal_minus_books_including_missing_and_paired_documents():
    rec = {
        "missing_in_books": [{"total_value": 100, "doc_type": "invoice"},
                             {"total_value": -30, "doc_type": "credit_note"}],
        "missing_in_gstr2_bills": [{"total": 20}],
        "missing_in_gstr2_expenses": [{"total": 10}],
        "missing_in_gstr2_credits": [{"total": 5}],
        "value_mismatches": [
            {"gstr2_doc": {"doc_type": "invoice"}, "gstr2_amount": 60, "books_amount": 50},
            {"gstr2_doc": {"doc_type": "credit_note"}, "gstr2_amount": 40, "books_amount": 25},
        ],
    }
    assert total_mismatch(rec) == Decimal("40.00")


def test_empty_and_decimal_precision():
    assert total_mismatch({}) == Decimal("0.00")
    assert total_mismatch({"missing_in_books": [
        {"total_value": "0.1"}, {"total_value": "0.2"}]}) == Decimal("0.30")


def test_invalid_amount_rejected():
    with pytest.raises(ValueError, match="finite"):
        total_mismatch({"missing_in_books": [{"total_value": "NaN"}]})
