import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.backfill_creator_matched_payments import (
    BackfillConfig,
    CreatorBooksPaymentLinkBackfill,
    build_native_payment_indexes,
    classify_links,
    find_creator_sequence_gaps,
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
        "location_id": "loc-1",
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
    def test_creator_sequence_gaps_are_crosschecked_against_all_payments(self):
        gaps = find_creator_sequence_gaps(
            [{"Payment_ID": 100}, {"Payment_ID": 104}],
            [{"Payment_ID": 101}, {"Payment_ID": 103}],
        )
        self.assertEqual(gaps, [{
            "first": 101, "last": 103,
            "found_in_creator": [101, 103],
            "missing_in_creator": [{"first": 102, "last": 102}],
        }])

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

    def test_unknown_payment_number_does_not_fallback(self):
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

        self.assertIsNone(resolved)
        self.assertEqual(source, "payment_number_missing")

    def test_creator_customer_lookup_uses_display_name_for_fallback(self):
        from workflows.creator_books_payment_link import _creator_values

        values = _creator_values(_creator_record(
            Customer_Name={"ID": "123", "Name": "Acme", "zc_display_value": "Acme"},
            PaymentNo="",
        ))
        payment = _books_payment(payment_number="BOOKS-99")
        resolved, source = resolve_books_payment(values, [payment], {}, {})

        self.assertIs(resolved, payment)
        self.assertEqual(source, "date_amount_reference_customer")

    def test_canonical_creator_payment_number_prevents_false_fallback(self):
        from workflows.creator_books_payment_link import _crosschecked_values

        matched = _creator_record(PaymentNo="")
        canonical = _creator_record(PaymentNo="PAY-0002")
        values = _crosschecked_values(matched, canonical)
        payments = [_books_payment(payment_number="PAY-0001"),
                    _books_payment(payment_id="books-payment-2", payment_number="PAY-0002")]
        by_id, by_number = build_native_payment_indexes(payments)

        payment, source = resolve_books_payment(values, payments, by_id, by_number)

        self.assertEqual(payment["payment_id"], "books-payment-2")
        self.assertEqual(source, "native_id_or_number")

    def test_ambiguous_payment_is_not_selected(self):
        payments = [
            _books_payment(payment_id="payment-1", payment_number="A"),
            _books_payment(payment_id="payment-2", payment_number="B"),
        ]

        resolved, source = resolve_books_payment(
            {
                "books_transaction_id": None,
                "books_payment_number": "",
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

    def test_existing_links_are_recognized_by_field_label(self):
        payment = _books_payment(custom_fields=[
            {"label": "Creator Record ID", "value": "creator-1"},
            {"label": "Creator Payment ID", "value": 101},
        ])

        status, missing = classify_links(payment, "creator-1", "101")

        self.assertEqual((status, missing), ("already_linked", []))

    def test_batch_execution_requires_explicit_permission(self):
        with self.assertRaisesRegex(ValueError, "--allow-batch"):
            BackfillConfig(location_id="loc-1", execute=True)


class TestCreatorBooksPaymentLinkBackfill(unittest.TestCase):
    def setUp(self):
        self.creator = MagicMock()
        self.books = MagicMock()
        self.creator.get_all_records.return_value = [_creator_record()]
        self.books.custom_fields.list_for_entity.return_value = _field_rows()
        self.books.customer_payments.list_all.return_value = [_books_payment()]
        self.books.customer_payments.get.return_value = {
            "customerpayment": _books_payment()
        }

    def test_dry_run_reports_ready_and_performs_no_writes(self):
        result = CreatorBooksPaymentLinkBackfill(
            self.creator,
            self.books,
            BackfillConfig(location_id="loc-1", ),
        ).run()

        self.assertEqual(result.summary(), {"scanned": 1, "ready": 1})
        self.books.customer_payments.list_all.assert_called_once_with()
        self.books.customer_payments.update.assert_not_called()
        self.books.customer_payments.create.assert_not_called()
        self.books.bank_transactions.match.assert_not_called()

    def test_books_payments_are_scoped_by_oldest_creator_date_and_location(self):
        self.creator.get_all_records.return_value = [
            _creator_record(Payment_ID=100, Payment_Date="2026-08-01"),
            _creator_record(ID="creator-2", Payment_ID=101, Payment_Date="2026-08-05", PaymentNo="PAY-0002"),
        ]
        self.books.customer_payments.list_all.return_value = [
            _books_payment(),
            _books_payment(payment_id="older", date="2026-07-31"),
            _books_payment(payment_id="elsewhere", location_id="loc-2"),
        ]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books, BackfillConfig(location_id="loc-1")
        ).run()

        self.assertEqual(result.oldest_creator_date, "2026-08-01")
        self.books.customer_payments.get.assert_not_called()

    def test_unmatched_books_payment_is_crosschecked_in_creator(self):
        self.creator.get_all_records.side_effect = [
            [_creator_record()],
            [_creator_record(), _creator_record(ID="creator-2", Payment_ID=102, PaymentNo="PAY-0002")],
        ]
        self.books.customer_payments.list_all.return_value = [
            _books_payment(), _books_payment(payment_id="books-payment-2", payment_number="PAY-0002")
        ]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books, BackfillConfig(location_id="loc-1")
        ).run()

        self.assertEqual(result.rows[-1]["status"], "creator_crosscheck_found")
        self.assertEqual(result.rows[-1]["creator_crosscheck_ids"], ["creator-2"])
        self.books.customer_payments.update.assert_not_called()

    def test_multiple_creator_claims_never_update_one_books_payment(self):
        self.creator.get_all_records.return_value = [
            _creator_record(), _creator_record(ID="creator-2", Payment_ID=102)
        ]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books,
            BackfillConfig(location_id="loc-1", execute=True, allow_batch=True),
        ).run()

        self.assertEqual([row["status"] for row in result.rows],
                         ["creator_match_ambiguous", "creator_match_ambiguous"])
        self.books.customer_payments.update.assert_not_called()

    def test_execute_updates_both_custom_fields_on_existing_payment(self):
        self.books.customer_payments.update.return_value = {"code": 0}
        self.books.customer_payments.get.side_effect = [
            {"customerpayment": _books_payment()},
            {"customerpayment": _books_payment(
                custom_fields=[
                    {"api_name": "cf_creator_record_id", "value": "creator-1"},
                    {"api_name": "cf_creator_payment_id", "value": "101"},
                ]
            )},
        ]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator,
            self.books,
            BackfillConfig(location_id="loc-1", execute=True, creator_record_id="creator-1"),
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
                BackfillConfig(location_id="loc-1", 
                    execute=True,
                    creator_record_id="creator-1",
                    checkpoint_path=checkpoint,
                ),
            ).run()
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(result.rows[0]["status"], "update_failed")
        self.assertEqual(saved["rows"][0]["status"], "update_failed")

    def test_rate_limit_is_retried_before_update_is_checkpointed(self):
        self.books.customer_payments.update.side_effect = [
            RuntimeError("API Error (code=44): request limit"), {"code": 0}
        ]
        self.books.customer_payments.get.side_effect = [
            {"customerpayment": _books_payment()},
            {"customerpayment": _books_payment(custom_fields=[
                {"api_name": "cf_creator_record_id", "value": "creator-1"},
                {"api_name": "cf_creator_payment_id", "value": "101"},
            ])},
        ]
        with patch("workflows.creator_books_payment_link.time.sleep") as sleep:
            result = CreatorBooksPaymentLinkBackfill(
                self.creator, self.books,
                BackfillConfig(location_id="loc-1", execute=True,
                               creator_record_id="creator-1",
                               books_request_interval_seconds=0),
            ).run()

        self.assertEqual(result.rows[0]["status"], "updated")
        self.assertEqual(self.books.customer_payments.update.call_count, 2)
        sleep.assert_any_call(65)

    def test_existing_links_are_not_written_again(self):
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
            BackfillConfig(location_id="loc-1", execute=True, creator_record_id="creator-1"),
        ).run()

        self.assertEqual(result.rows[0]["status"], "already_linked")
        self.books.customer_payments.update.assert_not_called()

    def test_list_custom_field_values_skip_unneeded_detail_read(self):
        self.books.customer_payments.list_all.return_value = [_books_payment(
            cf_creator_record_id="creator-1", cf_creator_payment_id=101,
        )]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books, BackfillConfig(location_id="loc-1")
        ).run()

        self.assertEqual(result.rows[0]["status"], "already_linked")
        self.books.customer_payments.get.assert_not_called()

    def test_missing_creator_payment_id_is_not_written(self):
        self.creator.get_all_records.return_value = [_creator_record(Payment_ID=None)]

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books,
            BackfillConfig(location_id="loc-1", execute=True, creator_record_id="creator-1"),
        ).run()

        self.assertEqual(result.rows[0]["status"], "creator_data_incomplete")
        self.books.customer_payments.update.assert_not_called()

    def test_conflicting_live_books_field_is_not_overwritten(self):
        self.books.customer_payments.get.return_value = {
            "customerpayment": _books_payment(custom_fields=[
                {"api_name": "cf_creator_record_id", "value": "another-record"}
            ])
        }

        result = CreatorBooksPaymentLinkBackfill(
            self.creator, self.books,
            BackfillConfig(location_id="loc-1", execute=True, creator_record_id="creator-1"),
        ).run()

        self.assertEqual(result.rows[0]["status"], "identifier_conflict")
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
                BackfillConfig(location_id="loc-1", resume_from=checkpoint),
            ).run()

        self.assertEqual(result.summary(), {"scanned": 1, "updated": 1})
        self.books.customer_payments.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
