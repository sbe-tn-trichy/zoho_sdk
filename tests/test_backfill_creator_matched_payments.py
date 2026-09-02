import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from apps.backfill_creator_matched_payments import (
    BackfillConfig,
    CreatorBooksPaymentLinkBackfill,
    build_native_payment_indexes,
    classify_links,
    resolve_books_payment,
)


def _creator_record(**overrides):
    values = {
        "ID": "creator-1",
        "Payment_ID": 101,
        "PaymentNo": "PAY-0001",
        "Payment_Date": "2026-08-01",
        "Payment_Amount": "500.00",
        "Reference": "UTR-101",
        "Customer_Name": "Acme",
    }
    values.update(overrides)
    return values


def _books_payment(**overrides):
    values = {
        "payment_id": "books-payment-1",
        "payment_number": "PAY-0001",
        "date": "2026-08-01",
        "amount": 500,
        "reference_number": "UTR-101",
        "customer_name": "Acme",
        "custom_fields": [],
    }
    values.update(overrides)
    return values


def _field_rows():
    return [
        {
            "field_id": "field-record",
            "api_name": "cf_creator_record_id",
            "data_type": "string",
            "is_unique": True,
        },
        {
            "field_id": "field-payment",
            "api_name": "cf_creator_payment_id",
            "data_type": "number",
            "is_unique": True,
        },
    ]


class TestBackfillHelpers(unittest.TestCase):
    def test_payment_number_resolves_existing_books_payment(self):
        payment = _books_payment()
        by_id, by_number = build_native_payment_indexes([payment])

        resolved, source = resolve_books_payment(
            {
                "books_transaction_id": None,
                "books_payment_number": "PAY-0001",
                "date": date(2026, 8, 1),
                "amount": Decimal("500"),
                "reference": "UTR-101",
                "customer_name": "Acme",
            },
            [payment],
            by_id,
            by_number,
        )

        self.assertIs(resolved, payment)
        self.assertEqual(source, "native_id_or_number")

    def test_unique_date_amount_reference_customer_fallback(self):
        payment = _books_payment(payment_number="BOOKS-99")

        resolved, source = resolve_books_payment(
            {
                "books_transaction_id": "bank-transaction-1",
                "books_payment_number": "UNKNOWN",
                "date": date(2026, 8, 1),
                "amount": Decimal("500"),
                "reference": "UTR-101",
                "customer_name": "Acme",
            },
            [payment],
            {},
            {},
        )

        self.assertIs(resolved, payment)
        self.assertEqual(source, "date_amount_reference_customer")

    def test_ambiguous_payment_is_not_selected(self):
        payments = [
            _books_payment(payment_id="payment-1", payment_number="A"),
            _books_payment(payment_id="payment-2", payment_number="B"),
        ]

        resolved, source = resolve_books_payment(
            {
                "books_transaction_id": None,
                "books_payment_number": "UNKNOWN",
                "date": date(2026, 8, 1),
                "amount": Decimal("500"),
                "reference": "UTR-101",
                "customer_name": "Acme",
            },
            payments,
            {},
            {},
        )

        self.assertIsNone(resolved)
        self.assertEqual(source, "payment_ambiguous")

    def test_duplicate_native_payment_number_is_ambiguous(self):
        payments = [
            _books_payment(payment_id="payment-1"),
            _books_payment(payment_id="payment-2"),
        ]
        by_id, by_number = build_native_payment_indexes(payments)

        resolved, source = resolve_books_payment(
            {"books_payment_number": "PAY-0001"},
            payments,
            by_id,
            by_number,
        )

        self.assertIsNone(resolved)
        self.assertEqual(source, "payment_ambiguous")

    def test_explicit_payment_id_wins_when_its_number_is_duplicated(self):
        payments = [
            _books_payment(payment_id="payment-1"),
            _books_payment(payment_id="payment-2"),
        ]
        by_id, by_number = build_native_payment_indexes(payments)

        resolved, source = resolve_books_payment(
            {
                "books_transaction_id": "payment-1",
                "books_payment_number": "PAY-0001",
            },
            payments,
            by_id,
            by_number,
        )

        self.assertIs(resolved, payments[0])
        self.assertEqual(source, "native_id_or_number")

    def test_conflicting_native_id_and_number_are_rejected(self):
        payments = [
            _books_payment(payment_id="payment-1", payment_number="PAY-1"),
            _books_payment(payment_id="payment-2", payment_number="PAY-2"),
        ]
        by_id, by_number = build_native_payment_indexes(payments)

        resolved, source = resolve_books_payment(
            {"books_transaction_id": "payment-1", "books_payment_number": "PAY-2"},
            payments,
            by_id,
            by_number,
        )

        self.assertIsNone(resolved)
        self.assertEqual(source, "identifier_conflict")

    def test_conflicting_existing_link_is_rejected(self):
        payment = _books_payment(
            custom_fields=[
                {"api_name": "cf_creator_record_id", "value": "another-record"}
            ]
        )

        status, missing = classify_links(payment, "creator-1", "101")

        self.assertEqual(status, "identifier_conflict")
        self.assertEqual(missing, [])

    def test_batch_execution_requires_explicit_permission(self):
        with self.assertRaisesRegex(ValueError, "--allow-batch"):
            BackfillConfig(execute=True)


class TestCreatorBooksPaymentLinkBackfill(unittest.TestCase):
    def setUp(self):
        self.creator = MagicMock()
        self.books = MagicMock()
        self.creator.get_all_records.return_value = [_creator_record()]
        self.books.custom_fields.list_for_entity.return_value = _field_rows()
        self.books.customer_payments.list_all.return_value = [_books_payment()]

    def test_dry_run_reports_ready_and_performs_no_writes(self):
        result = CreatorBooksPaymentLinkBackfill(
            self.creator,
            self.books,
            BackfillConfig(),
        ).run()

        self.assertEqual(result.summary(), {"scanned": 1, "ready": 1})
        self.books.customer_payments.update.assert_not_called()
        self.books.customer_payments.create.assert_not_called()
        self.books.bank_transactions.match.assert_not_called()

    def test_execute_updates_both_custom_fields_on_existing_payment(self):
        self.books.customer_payments.update.return_value = {"code": 0}
        self.books.customer_payments.get.return_value = {
            "customerpayment": _books_payment(
                custom_fields=[
                    {"api_name": "cf_creator_record_id", "value": "creator-1"},
                    {"api_name": "cf_creator_payment_id", "value": "101"},
                ]
            )
        }

        result = CreatorBooksPaymentLinkBackfill(
            self.creator,
            self.books,
            BackfillConfig(execute=True, creator_record_id="creator-1"),
        ).run()

        self.assertEqual(result.rows[0]["status"], "updated")
        self.books.customer_payments.update.assert_called_once_with(
            "books-payment-1",
            {
                "custom_fields": [
                    {"label": "Creator Record ID", "value": "creator-1"},
                    {"label": "Creator Payment ID", "value": "101"},
                ]
            },
        )
        self.books.customer_payments.create.assert_not_called()

    def test_failed_readback_is_recorded_and_checkpointed(self):
        self.books.customer_payments.update.return_value = {"code": 0}
        self.books.customer_payments.get.return_value = {
            "customerpayment": _books_payment(custom_fields=[])
        }
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            result = CreatorBooksPaymentLinkBackfill(
                self.creator,
                self.books,
                BackfillConfig(
                    execute=True,
                    creator_record_id="creator-1",
                    checkpoint_path=checkpoint,
                ),
            ).run()
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(result.rows[0]["status"], "update_failed")
        self.assertEqual(saved["rows"][0]["status"], "update_failed")

    def test_existing_links_are_not_written_again(self):
        self.books.customer_payments.list_all.return_value = [
            _books_payment(
                custom_fields=[
                    {"api_name": "cf_creator_record_id", "value": "creator-1"},
                    {"api_name": "cf_creator_payment_id", "value": "101"},
                ]
            )
        ]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator,
            self.books,
            BackfillConfig(execute=True, creator_record_id="creator-1"),
        ).run()

        self.assertEqual(result.rows[0]["status"], "already_linked")
        self.books.customer_payments.update.assert_not_called()

    def test_resume_skips_completed_record(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"creator_record_id": "creator-1", "status": "updated"}
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = CreatorBooksPaymentLinkBackfill(
                self.creator,
                self.books,
                BackfillConfig(resume_from=checkpoint),
            ).run()

        self.assertEqual(result.summary(), {"scanned": 1, "updated": 1})
        self.books.customer_payments.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
