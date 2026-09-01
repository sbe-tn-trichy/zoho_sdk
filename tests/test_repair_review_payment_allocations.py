import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from apps import repair_review_payment_allocations as MODULE


def _state():
    return {
        "entries": [
            {
                "id": "creator-1",
                "push_status": "pushed",
                "books_payment_id": "payment-1",
                "creator": {"date": "2026-08-01", "books_customer_id": "customer-1"},
            }
        ]
    }


def _payment(unused=100):
    return {
        "payment": {
            "payment_id": "payment-1",
            "customer_id": "customer-1",
            "payment_mode": "banktransfer",
            "amount": 100,
            "unused_amount": unused,
            "date": "2026-08-01",
            "reference_number": "REF",
            "description": "receipt",
            "account_id": "bank-1",
            "invoices": [],
        }
    }


def _invoice(balance=100):
    return {
        "invoice_id": "invoice-1",
        "invoice_number": "INV-1",
        "date": "2026-07-01",
        "due_date": "2026-07-31",
        "balance": balance,
        "status": "overdue",
    }


def test_dry_run_never_updates_books():
    books = MagicMock()
    books.customer_payments.get.return_value = _payment()
    books.invoices.list_all.return_value = [_invoice()]
    with tempfile.TemporaryDirectory() as directory:
        result = MODULE.run(
            books,
            _state(),
            execute=False,
            checkpoint_path=Path(directory) / "result.json",
        )
    assert result["summary"]["planned"] == 1
    assert result["summary"]["allocated_amount"] == 100.0
    books.customer_payments.update.assert_not_called()


def test_execute_updates_then_verifies_unused_amount():
    books = MagicMock()
    books.customer_payments.get.side_effect = [_payment(), _payment(unused=0)]
    books.invoices.list_all.return_value = [_invoice()]
    with tempfile.TemporaryDirectory() as directory:
        result = MODULE.run(
            books,
            _state(),
            execute=True,
            checkpoint_path=Path(directory) / "result.json",
        )
    assert result["summary"]["repaired"] == 1
    payload = books.customer_payments.update.call_args.args[1]
    assert payload["invoices"] == [
        {"invoice_id": "invoice-1", "amount_applied": 100.0}
    ]


def test_existing_invoice_allocation_is_preserved_and_extended():
    payment = _payment()
    payment["payment"]["invoices"] = [
        {"invoice_id": "invoice-1", "amount_applied": 50, "tax_amount_withheld": 0}
    ]
    payload = MODULE._update_payload(
        payment["payment"],
        [{"invoice_id": "invoice-1", "amount_applied": 25}],
    )
    assert payload["invoices"] == [
        {"invoice_id": "invoice-1", "amount_applied": 75.0}
    ]


def test_no_open_invoice_is_not_updated():
    books = MagicMock()
    books.customer_payments.get.return_value = _payment()
    books.invoices.list_all.return_value = []
    with tempfile.TemporaryDirectory() as directory:
        result = MODULE.run(
            books,
            _state(),
            execute=True,
            checkpoint_path=Path(directory) / "result.json",
        )
    assert result["summary"]["no_open_invoices"] == 1
    books.customer_payments.update.assert_not_called()
