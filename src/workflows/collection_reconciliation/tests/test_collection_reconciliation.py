import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from workflows.collection_reconciliation import (
    AUDIT_FIELD_REQUIREMENTS,
    COLLECTION_FIELD_REQUIREMENTS,
    CollectionReconciler,
    CollectionReconciliationConfig,
    REQUIRED_OAUTH_SCOPES,
    ensure_books_customer_payment_fields,
    missing_oauth_scopes,
    validate_creator_form_fields,
)


def _config(**overrides):
    values = {
        "creator_app_link_name": "collections",
        "bank_account_id": "bank-1",
        "dry_run": False,
    }
    values.update(overrides)
    return CollectionReconciliationConfig(**values)


class TestCollectionSchema(unittest.TestCase):
    @staticmethod
    def _creator_fields(requirements):
        return {
            "fields": [
                {
                    "link_name": requirement.api_name,
                    "type": requirement.allowed_types[0],
                    "choices": [
                        {"value": value} for value in requirement.required_choices
                    ],
                    **(
                        {"default_value": requirement.expected_default}
                        if requirement.expected_default
                        else {}
                    ),
                    **(
                        {"is_lookup_field": True}
                        if requirement.must_be_lookup
                        else {}
                    ),
                }
                for requirement in requirements
            ]
        }

    def test_creator_collection_schema_accepts_required_field_types(self):
        payload = self._creator_fields(COLLECTION_FIELD_REQUIREMENTS)
        result = validate_creator_form_fields(payload, COLLECTION_FIELD_REQUIREMENTS)
        self.assertTrue(result["valid"])
        self.assertEqual(result["missing"], [])

    def test_creator_collection_schema_reports_missing_and_wrong_types(self):
        payload = {"fields": [{"link_name": "Record_ID", "type": 1}]}
        result = validate_creator_form_fields(payload, COLLECTION_FIELD_REQUIREMENTS)
        self.assertFalse(result["valid"])
        self.assertEqual(result["wrong_types"][0]["field"], "Record_ID")
        self.assertIn("Payment_Date", result["missing"])

    def test_books_custom_fields_can_be_created_when_missing(self):
        books = MagicMock()
        books.custom_fields.list_for_entity.return_value = []
        books.custom_fields.create.side_effect = lambda data: {"field": data}

        result = ensure_books_customer_payment_fields(books, create_missing=True)

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["created"]), 2)
        labels = [call.args[0]["label"] for call in books.custom_fields.create.call_args_list]
        self.assertEqual(labels, ["Creator Record ID", "Creator Payment ID"])

    def test_books_custom_fields_report_non_unique_configuration(self):
        books = MagicMock()
        books.custom_fields.list_for_entity.return_value = [
            {"api_name": "cf_creator_record_id", "data_type": "string", "is_unique": False},
            {"api_name": "cf_creator_payment_id", "data_type": "number", "is_unique": True},
        ]

        result = ensure_books_customer_payment_fields(books)

        self.assertFalse(result["valid"])
        self.assertIn("field must be unique", result["misconfigured"][0]["problems"])

    def test_reconciler_validates_creator_and_books_schema(self):
        creator = MagicMock()
        books = MagicMock()
        creator.get_fields.side_effect = [
            self._creator_fields(COLLECTION_FIELD_REQUIREMENTS),
            self._creator_fields(AUDIT_FIELD_REQUIREMENTS),
        ]
        books.custom_fields.list_for_entity.return_value = [
            {"api_name": "cf_creator_record_id", "data_type": "string", "is_unique": True},
            {"api_name": "cf_creator_payment_id", "data_type": "number", "is_unique": True},
        ]

        report = CollectionReconciler(creator, books, _config()).validate_schema()

        self.assertTrue(report["creator_collection"]["valid"])
        self.assertTrue(report["creator_audit"]["valid"])
        self.assertTrue(report["books"]["valid"])


class TestCollectionReconciler(unittest.TestCase):
    def setUp(self):
        self.creator = MagicMock()
        self.books = MagicMock()
        self.analytics = MagicMock()

    def test_exact_match_selects_correct_reference_from_same_date_and_amount(self):
        self.creator.get_all_records.return_value = [
            {
                "Record_ID": "creator-1",
                "Payment_ID": 10001,
                "Payment_Date": "2026-08-01",
                "Amount": "500.00",
                "Payment_Mode": "Online",
                "Reference_Number": "UTR-222",
                "Customer_Name": {"ID": "customer-1"},
                "Reconciliation_Status": "Pending",
            }
        ]
        self.books.bank_transactions.list_all.return_value = [
            {
                "transaction_id": "tx-1",
                "date": "2026-08-01",
                "amount": 500,
                "reference_number": "UTR-111",
                "status": "uncategorized",
            },
            {
                "transaction_id": "tx-2",
                "date": "2026-08-01",
                "amount": 500,
                "reference_number": "UTR-222",
                "status": "uncategorized",
            },
        ]
        self.books.customer_payments.create.return_value = {
            "payment": {"payment_id": "payment-2"}
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {"transaction_id": "payment-2", "transaction_type": "customer_payment"}
            ]
        }

        result = CollectionReconciler(
            self.creator,
            self.books,
            _config(),
            self.analytics,
        ).reconcile_pending()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["confirmed"][0]["bank_transaction_id"], "tx-2")
        payload = self.books.customer_payments.create.call_args.args[0]
        self.assertEqual(payload["customer_id"], "customer-1")
        self.assertEqual(payload["payment_mode"], "banktransfer")
        self.assertEqual(
            payload["custom_fields"][0],
            {"label": "Creator Record ID", "value": "creator-1"},
        )
        self.assertEqual(
            payload["custom_fields"][1],
            {"label": "Creator Payment ID", "value": 10001},
        )
        self.assertEqual(self.creator.update_records.call_count, 2)
        self.books.bank_transactions.match.assert_called_once_with(
            "tx-2",
            [
                {
                    "transaction_id": "payment-2",
                    "transaction_type": "customer_payment",
                }
            ],
        )
        self.creator.update_records.assert_called_with(
            "collections",
            "Collection_Records",
            {
                "data": {
                    "Reconciliation_Status": "Confirmed",
                    "Zoho_Books_Payment_ID": "payment-2",
                }
            },
            record_id="creator-1",
        )

    def test_reference_can_match_inside_bank_narration(self):
        record = {
            "Record_ID": "creator-1",
            "Payment_Date": "2026-08-01",
            "Amount": 100,
            "Reference_Number": "ABC123",
        }
        transaction = {
            "transaction_id": "tx-1",
            "date": "2026-08-01",
            "amount": 100,
            "description": "NEFT RECEIVED ABC123 CUSTOMER",
        }
        reconciler = CollectionReconciler(self.creator, self.books, _config())

        matched, reason = reconciler._find_transaction(record, [transaction], set())

        self.assertEqual(matched, transaction)
        self.assertEqual(reason, "exact_reference_amount_date")

    def test_unmatched_record_returns_analytics_suggestions_and_writes_audit(self):
        record = {
            "Record_ID": "creator-3",
            "Payment_Date": "2026-08-02",
            "Amount": "750",
            "Reference_Number": "UNKNOWN",
        }
        self.creator.get_all_records.return_value = [record]
        self.books.bank_transactions.list_all.return_value = []
        self.analytics.queries.execute.return_value = [
            {"Customer ID": "customer-7", "Match_Confidence": 92}
        ]
        reconciler = CollectionReconciler(
            self.creator,
            self.books,
            _config(analytics_workspace_id="workspace-1"),
            self.analytics,
        )

        result = reconciler.reconcile_pending()

        self.assertEqual(result["confirmed"], [])
        self.assertEqual(result["unmatched"][0]["analytics_suggestions"][0]["Customer ID"], "customer-7")
        self.analytics.queries.execute.assert_called_once()
        self.creator.add_records.assert_called_once()
        audit_payload = self.creator.add_records.call_args.args[2]["data"][0]
        self.assertEqual(audit_payload["Creator_Record_ID"], "creator-3")
        self.assertEqual(audit_payload["Stage"], "matching")

    def test_manual_analytics_resolution_creates_creator_and_books_records(self):
        self.creator.add_records.return_value = {
            "result": [{"data": {"ID": "creator-manual-1", "Payment_ID": 99001}}]
        }
        self.books.customer_payments.create.return_value = {
            "customerpayment": {"payment_id": "payment-manual-1"}
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "payment-manual-1",
                    "transaction_type": "customer_payment",
                }
            ]
        }
        reconciler = CollectionReconciler(self.creator, self.books, _config())

        result = reconciler.resolve_manual(
            {
                "transaction_id": "bank-tx-9",
                "date": "2026-08-03",
                "amount": "1250.00",
                "reference_number": "UTR-MANUAL",
                "description": "ACME RECEIPT",
            },
            {"Customer ID": "customer-9", "Customer Name": "Acme"},
        )

        self.assertEqual(result["source"], "Manual_Analytics")
        self.assertEqual(result["books_payment_id"], "payment-manual-1")
        create_payload = self.creator.add_records.call_args.args[2]["data"][0]
        self.assertEqual(create_payload["Reconciliation_Status"], "Pending")
        self.assertEqual(create_payload["Customer_Name"], "customer-9")
        payment_payload = self.books.customer_payments.create.call_args.args[0]
        self.assertEqual(payment_payload["customer_id"], "customer-9")
        self.assertEqual(
            payment_payload["custom_fields"],
            [
                {"label": "Creator Record ID", "value": "creator-manual-1"},
                {"label": "Creator Payment ID", "value": "99001"},
            ],
        )

    def test_dry_run_does_not_write_to_creator_or_books(self):
        self.creator.get_all_records.return_value = [
            {
                "Record_ID": "creator-dry",
                "Payment_Date": "2026-08-01",
                "Amount": 25,
                "Payment_Mode": "Cash",
                "Reference_Number": "DRY-1",
                "Customer_Name": {"ID": "customer-1"},
            }
        ]
        self.books.bank_transactions.list_all.return_value = [
            {
                "transaction_id": "tx-dry",
                "date": "2026-08-01",
                "amount": 25,
                "reference_number": "DRY-1",
            }
        ]
        result = CollectionReconciler(
            self.creator,
            self.books,
            _config(dry_run=True, amount_tolerance=Decimal("0")),
        ).reconcile_pending()

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["confirmed"][0]["books_payment_id"], "dry-run:tx-dry")
        self.books.customer_payments.create.assert_not_called()
        self.creator.update_records.assert_not_called()

    def test_existing_books_payment_must_be_returned_as_match_candidate(self):
        self.creator.get_all_records.return_value = [
            {
                "Record_ID": "creator-existing",
                "Payment_Date": "2026-08-01",
                "Amount": 80,
                "Reference_Number": "EXIST-1",
                "Customer_Name": {"ID": "customer-1"},
                "Zoho_Books_Payment_ID": "payment-existing",
            }
        ]
        self.books.bank_transactions.list_all.return_value = [
            {
                "transaction_id": "tx-existing",
                "date": "2026-08-01",
                "amount": 80,
                "reference_number": "EXIST-1",
            }
        ]
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "payment-existing",
                    "transaction_type": "customer_payment",
                }
            ]
        }

        result = CollectionReconciler(self.creator, self.books, _config()).reconcile_pending()

        self.assertEqual(result["confirmed"][0]["books_payment_id"], "payment-existing")
        self.books.bank_transactions.match.assert_called_once_with(
            "tx-existing",
            [
                {
                    "transaction_id": "payment-existing",
                    "transaction_type": "customer_payment",
                }
            ],
        )
        self.books.customer_payments.create.assert_not_called()

    def test_creator_confirmation_failure_rolls_back_books_match(self):
        self.creator.get_all_records.return_value = [
            {
                "Record_ID": "creator-rollback",
                "Payment_Date": "2026-08-01",
                "Amount": 90,
                "Reference_Number": "ROLLBACK-1",
                "Customer_Name": {"ID": "customer-1"},
                "Zoho_Books_Payment_ID": "payment-rollback",
            }
        ]
        self.books.bank_transactions.list_all.return_value = [
            {
                "transaction_id": "tx-rollback",
                "date": "2026-08-01",
                "amount": 90,
                "reference_number": "ROLLBACK-1",
            }
        ]
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "payment-rollback",
                    "transaction_type": "customer_payment",
                }
            ]
        }
        self.creator.update_records.side_effect = RuntimeError("Creator unavailable")

        result = CollectionReconciler(self.creator, self.books, _config()).reconcile_pending()

        self.assertEqual(result["confirmed"], [])
        self.assertEqual(result["failed"][0]["creator_record_id"], "creator-rollback")
        self.books.bank_transactions.unmatch.assert_called_once_with(
            "tx-rollback",
            "bank-1",
        )

    def test_ambiguous_duplicate_bank_lines_are_not_auto_matched(self):
        record = {
            "Record_ID": "creator-ambiguous",
            "Payment_Date": "2026-08-01",
            "Amount": 100,
            "Reference_Number": "DUPLICATE-1",
        }
        transactions = [
            {
                "transaction_id": transaction_id,
                "date": "2026-08-01",
                "amount": 100,
                "reference_number": "DUPLICATE-1",
            }
            for transaction_id in ("tx-a", "tx-b")
        ]

        matched, reason = CollectionReconciler(
            self.creator,
            self.books,
            _config(),
        )._find_transaction(record, transactions, set())

        self.assertIsNone(matched)
        self.assertIn("Multiple", reason)

    def test_icici_upi_reference_is_extracted_from_bank_description(self):
        record = {
            "Record_ID": "creator-icici",
            "Payment_Date": "2026-08-12",
            "Amount": 1000,
            "Reference_Number": "622494425255",
        }
        transaction = {
            "transaction_id": "tx-icici",
            "date": "2026-08-12",
            "amount": 1000,
            "reference_number": "S78528277",
            "description": "UPI/622494425255/UPI/customer@bank/BANK/AXI123",
        }
        config = _config(bank_account_id="1094368000056644467")

        matched, reason = CollectionReconciler(
            self.creator,
            self.books,
            config,
        )._find_transaction(record, [transaction], set())

        self.assertIs(matched, transaction)
        self.assertEqual(reason, "exact_reference_amount_date")


class TestCollectionScopes(unittest.TestCase):
    def test_missing_oauth_scopes(self):
        missing = missing_oauth_scopes(REQUIRED_OAUTH_SCOPES[:-1])
        self.assertEqual(missing, ["ZohoAnalytics.data.read"])


if __name__ == "__main__":
    unittest.main()
