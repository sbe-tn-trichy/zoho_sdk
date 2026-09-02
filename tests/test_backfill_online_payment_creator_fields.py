from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from apps.backfill_online_payment_creator_fields import find_books_payment, run_backfill


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


def test_batch_execution_requires_explicit_permission():
    with pytest.raises(ValueError, match="--allow-batch"):
        run_backfill(MagicMock(), MagicMock(), creator_app="app", execute=True)


def test_execute_verifies_creator_checkpoint(tmp_path: Path):
    creator = MagicMock()
    books = MagicMock()
    creator.get_all_records.return_value = [
        {
            "ID": "record-1",
            "Payment_Date": "2026-08-29",
            "Payment_Amount": "500",
            "Reference": "UTR-100",
            "Customer_Name": {"Customer_Id": "customer-1"},
        }
    ]
    books.customer_payments.list_all.return_value = [_payment()]
    creator.update_records.return_value = {"code": 3000}
    creator.get_records.return_value = {
        "data": [
            {
                "ID": "record-1",
                "Books_Transaction_Id": "payment-1",
                "PaymentNo": "PAY-1",
            }
        ]
    }
    checkpoint = tmp_path / "checkpoint.json"

    result = run_backfill(
        creator,
        books,
        creator_app="app",
        execute=True,
        creator_record_id="record-1",
        checkpoint_path=checkpoint,
    )

    assert result["summary"] == {"scanned": 1, "updated": 1}
    assert checkpoint.exists()


def test_failed_creator_readback_is_reported(tmp_path: Path):
    creator = MagicMock()
    books = MagicMock()
    creator.get_all_records.return_value = [
        {
            "ID": "record-1",
            "Payment_Date": "2026-08-29",
            "Payment_Amount": "500",
            "Reference": "UTR-100",
            "Customer_Name": {"Customer_Id": "customer-1"},
        }
    ]
    books.customer_payments.list_all.return_value = [_payment()]
    creator.update_records.return_value = {"code": 3000}
    creator.get_records.return_value = {"data": []}

    result = run_backfill(
        creator,
        books,
        creator_app="app",
        execute=True,
        creator_record_id="record-1",
        checkpoint_path=tmp_path / "checkpoint.json",
    )

    assert result["summary"] == {"scanned": 1, "update_failed": 1}


def test_resume_skips_verified_updated_record(tmp_path: Path):
    creator = MagicMock()
    books = MagicMock()
    creator.get_all_records.return_value = [{"ID": "record-1"}]
    books.customer_payments.list_all.return_value = []
    resume = tmp_path / "resume.json"
    resume.write_text(
        '{"rows":[{"record_id":"record-1","status":"updated"}]}',
        encoding="utf-8",
    )

    result = run_backfill(
        creator,
        books,
        creator_app="app",
        execute=True,
        allow_batch=True,
        resume_from=resume,
    )

    assert result["summary"] == {"scanned": 1, "updated": 1}
    creator.update_records.assert_not_called()
