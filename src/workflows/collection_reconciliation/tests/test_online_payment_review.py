import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflows.collection_reconciliation.review import (
    OnlinePaymentReviewConfig,
    OnlinePaymentReviewService,
)
from workflows.core.exceptions import ReconciliationError
from workflows.core.config import Config


class TestOnlinePaymentReviewService(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.creator = MagicMock()
        self.books = MagicMock()
        self.config = OnlinePaymentReviewConfig(
            creator_app_link_name="app",
            bank_account_id="bank-1",
            state_path=Path(self.temporary.name) / "review.json",
        )
        self.service = OnlinePaymentReviewService(
            self.creator, self.books, self.config
        )
        self.payment = {
            "ID": "creator-1",
            "Payment_ID": "501",
            "Payment_Date": "2026-07-12",
            "Payment_Amount": "1250.00",
            "Reference": "UPI123",
            "Customer_Name": {
                "ID": "creator-customer-1",
                "zc_display_value": "Example Customer",
            },
        }
        self.customer = {
            "ID": "creator-customer-1",
            "Customer_Id": "books-customer-1",
        }
        self.bank = {
            "transaction_id": "bank-tx-1",
            "date": "2026-07-12",
            "amount": 1250,
            "reference_number": "UPI123",
            "description": "UPI receipt",
        }
        self.invoice = {
            "invoice_id": "invoice-1",
            "invoice_number": "INV-1",
            "date": "2026-06-01",
            "due_date": "2026-07-01",
            "balance": 20000,
            "status": "overdue",
        }
        self.books.invoices.list_all.return_value = [self.invoice]
        self.creator.update_records.return_value = {
            "code": 3000,
            "data": {"ID": "creator-1"},
        }
        self.creator.get_records.return_value = {
            "data": [
                {
                    "ID": "creator-1",
                    "Books_Transaction_Id": "books-payment-1",
                    "PaymentNo": "PAY-0001",
                }
            ]
        }

    def _refresh(self):
        self.creator.get_all_records.side_effect = [
            [self.payment],
            [self.customer],
        ]
        self.books.bank_transactions.list_all.return_value = [self.bank]
        return self.service.refresh()

    def test_refresh_builds_reviewable_exact_match(self):
        batch = self._refresh()

        self.assertEqual(
            batch["reports"],
            [{"payment_type": "Online", "report": "Online_Payments"}],
        )
        self.assertEqual(len(batch["entries"]), 1)
        entry = batch["entries"][0]
        self.assertTrue(entry["reviewable"])
        self.assertEqual(entry["creator"]["amount"], "1250.00")
        self.assertEqual(entry["creator"]["books_customer_id"], "books-customer-1")
        self.assertEqual(entry["bank"]["transaction_id"], "bank-tx-1")
        self.assertEqual(entry["allocation_status"], "fully_allocated")
        self.assertEqual(entry["invoice_allocations"][0]["amount_applied"], 1250.0)

    def test_refresh_preserves_ambiguous_bank_candidates_for_review(self):
        second_bank = {
            **self.bank,
            "transaction_id": "bank-tx-2",
            "description": "Second matching UPI receipt",
        }
        self.creator.get_all_records.side_effect = [
            [self.payment],
            [self.customer],
        ]
        self.books.bank_transactions.list_all.return_value = [self.bank, second_bank]

        entry = self.service.refresh()["entries"][0]

        self.assertFalse(entry["reviewable"])
        self.assertIsNone(entry["bank"])
        self.assertEqual(entry["reason"], "Multiple bank transactions match")
        self.assertEqual(
            [row["transaction_id"] for row in entry["ambiguous_candidates"]],
            ["bank-tx-1", "bank-tx-2"],
        )
        self.assertEqual(entry["possible_candidates"], [])

    def test_refresh_preserves_date_amount_candidate_when_reference_differs(self):
        self.bank["reference_number"] = "DIFFERENT-REFERENCE"
        self.creator.get_all_records.side_effect = [
            [self.payment],
            [self.customer],
        ]
        self.books.bank_transactions.list_all.return_value = [self.bank]

        entry = self.service.refresh()["entries"][0]

        self.assertFalse(entry["reviewable"])
        self.assertIsNone(entry["bank"])
        self.assertEqual(entry["reason"], "No bank transaction matched")
        self.assertEqual(entry["ambiguous_candidates"], [])
        self.assertEqual(
            [row["transaction_id"] for row in entry["possible_candidates"]],
            ["bank-tx-1"],
        )

    def test_possible_match_can_be_explicitly_selected_and_pushed(self):
        self.bank["reference_number"] = "DIFFERENT-REFERENCE"
        self.creator.get_all_records.side_effect = [
            [self.payment],
            [self.customer],
        ]
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.service.refresh()
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }

        with self.assertRaisesRegex(
            ReconciliationError,
            "Explicit confirmation",
        ):
            self.service.accept_and_push(
                "creator-1",
                selected_bank_transaction_id="bank-tx-1",
            )

        pushed = self.service.accept_and_push(
            "creator-1",
            selected_bank_transaction_id="bank-tx-1",
            allow_reference_override=True,
        )

        self.assertEqual(pushed["push_status"], "pushed")
        self.assertTrue(pushed["manual_reference_override"])
        self.assertEqual(pushed["bank"]["transaction_id"], "bank-tx-1")
        self.books.bank_transactions.match.assert_called_once()

    def test_reject_is_local_and_persistent(self):
        self._refresh()

        rejected = self.service.reject("creator-1")

        self.assertEqual(rejected["decision"], "rejected")
        saved = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["entries"][0]["decision"], "rejected")
        self.books.customer_payments.create.assert_not_called()
        self.creator.update_records.assert_not_called()

    def test_accept_creates_matches_and_updates_creator_once(self):
        self._refresh()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }

        pushed = self.service.accept_and_push("creator-1")
        pushed_again = self.service.accept_and_push("creator-1")

        self.assertEqual(pushed["push_status"], "pushed")
        self.assertEqual(pushed_again["books_payment_id"], "books-payment-1")
        self.assertEqual(pushed_again["books_payment_number"], "PAY-0001")
        create_payload = self.books.customer_payments.create.call_args.args[0]
        self.assertEqual(create_payload["customer_id"], "books-customer-1")
        self.assertEqual(create_payload["amount"], 1250.0)
        self.assertEqual(
            create_payload["invoices"],
            [{"invoice_id": "invoice-1", "amount_applied": 1250.0}],
        )
        self.books.customer_payments.create.assert_called_once()
        self.books.bank_transactions.match.assert_called_once_with(
            "bank-tx-1",
            [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ],
        )
        self.creator.update_records.assert_called_once_with(
            "app",
            "All_Payments",
            {
                "data": {
                    "Books_Transaction_Id": "books-payment-1",
                    "PaymentNo": "PAY-0001",
                }
            },
            record_id="creator-1",
        )
        self.creator.get_records.assert_called_once_with(
            "app",
            "All_Payments",
            params={"criteria": "ID == creator-1", "field_config": "all"},
        )

    def test_missing_create_payment_number_is_loaded_before_creator_checkpoint(self):
        self._refresh()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {"payment_id": "books-payment-1"}
        }
        self.books.customer_payments.get.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }

        pushed = self.service.accept_and_push("creator-1")

        self.assertEqual(pushed["books_payment_number"], "PAY-0001")
        self.books.customer_payments.get.assert_called_once_with("books-payment-1")

    def test_accept_matches_single_invoice_application_candidate(self):
        self._refresh()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "invoice-payment-1",
                    "transaction_type": "customer_payment",
                }
            ]
        }
        self.books.customer_payments.get.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
                "invoices": [{"invoice_payment_id": "invoice-payment-1"}],
            }
        }

        pushed = self.service.accept_and_push("creator-1")

        self.assertEqual(pushed["push_status"], "pushed")
        self.books.bank_transactions.match.assert_called_once_with(
            "bank-tx-1",
            [
                {
                    "transaction_id": "invoice-payment-1",
                    "transaction_type": "customer_payment",
                }
            ],
        )
        checkpoint = self.creator.update_records.call_args.args[2]["data"]
        self.assertEqual(checkpoint["Books_Transaction_Id"], "books-payment-1")

    def test_single_invoice_candidate_retry_reuses_existing_payment(self):
        self._refresh()
        batch = self.service.load()
        batch["entries"][0].update(
            {
                "decision": "accepted",
                "push_status": "failed",
                "retry_stage": "payment_created",
                "books_payment_id": "books-payment-1",
                "books_payment_number": "PAY-0001",
            }
        )
        self.service._save(batch)
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "invoice-payment-1",
                    "transaction_type": "customer_payment",
                }
            ]
        }
        self.books.customer_payments.get.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
                "invoices": [{"invoice_payment_id": "invoice-payment-1"}],
            }
        }

        pushed = self.service.accept_and_push("creator-1")

        self.assertEqual(pushed["push_status"], "pushed")
        self.books.customer_payments.create.assert_not_called()
        self.books.bank_transactions.match.assert_called_once_with(
            "bank-tx-1",
            [
                {
                    "transaction_id": "invoice-payment-1",
                    "transaction_type": "customer_payment",
                }
            ],
        )

    def test_creator_checkpoint_failure_retries_without_duplicate_books_payment(self):
        self._refresh()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }
        self.creator.get_records.return_value = {"data": [{"ID": "creator-1"}]}

        with self.assertRaisesRegex(
            ReconciliationError, "Creator checkpoint verification failed"
        ):
            self.service.accept_and_push("creator-1")

        failed = self.service.load()["entries"][0]
        self.assertEqual(failed["push_status"], "failed")
        self.assertEqual(failed["retry_stage"], "bank_matched")
        self.assertEqual(failed["books_payment_id"], "books-payment-1")

        self.creator.get_records.return_value = {
            "data": [
                {
                    "ID": "creator-1",
                    "Books_Transaction_Id": "books-payment-1",
                    "PaymentNo": "PAY-0001",
                }
            ]
        }
        pushed = self.service.accept_and_push("creator-1")

        self.assertEqual(pushed["push_status"], "pushed")
        self.books.customer_payments.create.assert_called_once()
        self.books.bank_transactions.match.assert_called_once()
        self.assertEqual(self.creator.update_records.call_count, 2)

    def test_creator_application_error_is_not_marked_pushed(self):
        self._refresh()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }
        self.creator.update_records.return_value = {
            "code": 3001,
            "message": "Field validation failed",
        }

        with self.assertRaisesRegex(ReconciliationError, "code=3001"):
            self.service.accept_and_push("creator-1")

        failed = self.service.load()["entries"][0]
        self.assertEqual(failed["push_status"], "failed")
        self.assertEqual(failed["retry_stage"], "bank_matched")
        self.creator.get_records.assert_not_called()

    def test_accept_many_uses_one_live_bank_snapshot(self):
        self._refresh()
        self.books.bank_transactions.list_all.reset_mock()
        self.books.bank_transactions.list_all.return_value = [self.bank]
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }

        result = self.service.accept_many(["creator-1", "creator-1"])

        self.assertEqual(result["selected"], 1)
        self.assertEqual(len(result["pushed"]), 1)
        self.assertEqual(result["failed"], [])
        self.books.bank_transactions.list_all.assert_called_once()

    def test_unmatched_entry_cannot_be_accepted(self):
        self.creator.get_all_records.side_effect = [[self.payment], [self.customer]]
        self.books.bank_transactions.list_all.return_value = []
        self.service.refresh()

        with self.assertRaisesRegex(ReconciliationError, "no unique bank match"):
            self.service.accept_and_push("creator-1")

    def test_no_open_invoice_blocks_push_to_prevent_unused_credit(self):
        self.books.invoices.list_all.return_value = []
        entry = self._refresh()["entries"][0]

        self.assertFalse(entry["reviewable"])
        self.assertEqual(entry["allocation_status"], "no_open_invoices")
        with self.assertRaisesRegex(ReconciliationError, "No open customer invoices"):
            self.service.accept_and_push("creator-1")
        self.books.customer_payments.create.assert_not_called()

    def test_accept_refreshes_and_allocates_oldest_due_first(self):
        newer = {
            "invoice_id": "invoice-new",
            "invoice_number": "INV-NEW",
            "date": "2026-06-01",
            "due_date": "2026-07-20",
            "balance": 1000,
            "status": "sent",
        }
        older = {
            "invoice_id": "invoice-old",
            "invoice_number": "INV-OLD",
            "date": "2026-05-01",
            "due_date": "2026-06-20",
            "balance": 750,
            "status": "overdue",
        }
        self.books.invoices.list_all.return_value = [newer, older]
        entry = self._refresh()["entries"][0]
        self.assertEqual(
            [row["invoice_id"] for row in entry["invoice_allocations"]],
            ["invoice-old", "invoice-new"],
        )
        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }

        self.service.accept_and_push("creator-1")

        payload = self.books.customer_payments.create.call_args.args[0]
        self.assertEqual(
            payload["invoices"],
            [
                {"invoice_id": "invoice-old", "amount_applied": 750.0},
                {"invoice_id": "invoice-new", "amount_applied": 500.0},
            ],
        )
        self.assertEqual(self.service.load()["entries"][0]["unallocated_amount"], 0.0)

    def test_partial_allocation_leaves_only_excess_unused(self):
        self.invoice["balance"] = 500
        entry = self._refresh()["entries"][0]

        self.assertTrue(entry["reviewable"])
        self.assertEqual(entry["allocation_status"], "partially_allocated")
        self.assertEqual(entry["unallocated_amount"], 750.0)

    def test_amount_tolerance_is_explicit(self):
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_account_id="bank-1",
                amount_tolerance=Decimal("0.50"),
                state_path=Path(self.temporary.name) / "tolerant.json",
            ),
        )
        self.bank["amount"] = 1250.25
        self.creator.get_all_records.side_effect = [[self.payment], [self.customer]]
        self.books.bank_transactions.list_all.return_value = [self.bank]

        self.assertTrue(service.refresh()["entries"][0]["reviewable"])

    def test_refresh_preserves_pushed_entry_when_bank_match_disappears(self):
        self._refresh()
        batch = self.service.load()
        batch["entries"][0].update(
            {
                "decision": "accepted",
                "push_status": "pushed",
                "books_payment_id": "books-payment-1",
            }
        )
        self.service._save(batch)
        self.creator.get_all_records.side_effect = [[self.payment], [self.customer]]
        self.books.bank_transactions.list_all.return_value = []

        refreshed = self.service.refresh()

        entry = refreshed["entries"][0]
        self.assertEqual(entry["push_status"], "pushed")
        self.assertEqual(entry["books_payment_id"], "books-payment-1")

    def test_refresh_combines_banks_and_labels_icici_suffix_match(self):
        icici_account_id = "test-icici-account"
        self.payment.update(
            {
                "Payment_Date": "2026-08-26",
                "Payment_Amount": "2000.00",
                "Reference": "0826",
            }
        )
        icici_transaction = {
            "transaction_id": "icici-tx-1",
            "date": "2026-08-26",
            "amount": 2000,
            "reference_number": "short-zoho-reference",
            "description": "UPI/313296200826/receipt",
        }
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_accounts=(
                    ("HDFC", "hdfc-1"),
                    ("ICICI", icici_account_id),
                    ("IDFC", "idfc-1"),
                ),
                state_path=Path(self.temporary.name) / "multi-bank.json",
            ),
        )
        self.creator.get_all_records.side_effect = [[self.payment], [self.customer]]
        self.books.bank_transactions.list_all.side_effect = [
            [],
            [icici_transaction],
            [],
        ]

        with patch.object(Config, "BANK_ACCOUNT_ICICI", icici_account_id):
            entry = service.refresh()["entries"][0]

        self.assertTrue(entry["reviewable"])
        self.assertEqual(entry["bank_name"], "ICICI")
        self.assertEqual(entry["bank_account_id"], icici_account_id)
        self.assertEqual(entry["bank"]["reference"], "313296200826")

    def test_cheque_report_uses_presented_date_and_books_check_mode(self):
        cheque = dict(self.payment)
        cheque.pop("Payment_Date")
        cheque["Cheque_Date"] = "2026-04-14"
        cheque["Reference"] = "1234"
        detail = {
            "ID": "cheque-detail-1",
            "Cheque_Number": "1234",
            "Presented_Date": "2026-07-12",
            "Payment_ID.Customer_Name": cheque["Customer_Name"],
        }
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_account_id="bank-1",
                payment_reports=(
                    ("Online", "Online_Payments"),
                    ("Cheque", "Cheques"),
                ),
                state_path=Path(self.temporary.name) / "cheques.json",
            ),
        )
        self.creator.get_all_records.side_effect = [
            [],
            [cheque],
            [detail],
            [self.customer],
        ]
        bank = dict(self.bank)
        bank["reference_number"] = "00001234"
        self.books.bank_transactions.list_all.return_value = [bank]
        entry = service.refresh()["entries"][0]
        self.assertEqual(entry["payment_type"], "Cheque")
        self.assertEqual(entry["source_report"], "Cheques")
        self.assertEqual(entry["creator"]["date"], "2026-07-12")

        self.books.customer_payments.create.return_value = {
            "payment": {
                "payment_id": "books-payment-1",
                "payment_number": "PAY-0001",
            }
        }
        self.books.bank_transactions.get_matches.return_value = {
            "matching_transactions": [
                {
                    "transaction_id": "books-payment-1",
                    "transaction_type": "customerpayment",
                }
            ]
        }
        service.accept_and_push("creator-1")

        payload = self.books.customer_payments.create.call_args.args[0]
        self.assertEqual(payload["payment_mode"], "check")
        self.creator.update_records.assert_called_once_with(
            "app",
            "All_Payments",
            {
                "data": {
                    "Books_Transaction_Id": "books-payment-1",
                    "PaymentNo": "PAY-0001",
                }
            },
            record_id="creator-1",
        )

    def test_cheque_match_allows_clearing_date_delay(self):
        cheque = dict(self.payment)
        cheque.pop("Payment_Date")
        cheque["Cheque_Date"] = "2026-08-22"
        cheque["Payment_Amount"] = "9105.00"
        cheque["Reference"] = "001034"
        detail = {
            "ID": "cheque-detail-1",
            "Cheque_Number": "1034",
            "Presented_Date": "2026-08-22",
            "Payment_ID.Customer_Name": cheque["Customer_Name"],
        }
        bank = {
            "transaction_id": "idfc-cheque-1",
            "date": "2026-08-24",
            "amount": 9105,
            "reference_number": "001034",
            "description": "BB/CHQ DEP/001034/22-08-2026",
        }
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_accounts=(("IDFC", "idfc-1"),),
                payment_reports=(("Cheque", "Cheques"),),
                state_path=Path(self.temporary.name) / "cheque-delay.json",
            ),
        )
        self.creator.get_all_records.side_effect = [[cheque], [detail], [self.customer]]
        self.books.bank_transactions.list_all.return_value = [bank]

        entry = service.refresh()["entries"][0]

        self.assertTrue(entry["reviewable"])
        self.assertEqual(entry["bank_name"], "IDFC")
        self.assertEqual(entry["creator"]["date_tolerance_days"], 7)

    def test_cheque_match_uses_last_four_digits_in_hdfc_narration(self):
        cheque = dict(self.payment)
        cheque.pop("Payment_Date")
        cheque["Payment_Amount"] = "9105.00"
        cheque["Reference"] = "5131"
        detail = {
            "ID": "cheque-detail-1",
            "Cheque_Number": "5131",
            "Presented_Date": "2026-08-22",
            "Payment_ID.Customer_Name": cheque["Customer_Name"],
        }
        bank = {
            "transaction_id": "hdfc-cheque-1",
            "date": "2026-08-22",
            "amount": 9105,
            "reference_number": "HDFC deposit",
            "description": "CHQ DEP/00005131/22-08-2026",
        }
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_accounts=(("HDFC", "hdfc-1"),),
                payment_reports=(("Cheque", "Cheques"),),
                state_path=Path(self.temporary.name) / "cheque-suffix.json",
            ),
        )
        self.creator.get_all_records.side_effect = [[cheque], [detail], [self.customer]]
        self.books.bank_transactions.list_all.return_value = [bank]

        entry = service.refresh()["entries"][0]

        self.assertTrue(entry["reviewable"])
        self.assertEqual(entry["bank_name"], "HDFC")

    def test_cheque_without_presented_detail_is_not_reviewable(self):
        cheque = dict(self.payment)
        cheque.pop("Payment_Date")
        cheque["Cheque_Date"] = "2026-07-12"
        service = OnlinePaymentReviewService(
            self.creator,
            self.books,
            OnlinePaymentReviewConfig(
                creator_app_link_name="app",
                bank_account_id="bank-1",
                payment_reports=(("Cheque", "Cheques"),),
                state_path=Path(self.temporary.name) / "unpresented-cheque.json",
            ),
        )
        self.creator.get_all_records.side_effect = [[cheque], [], [self.customer]]
        self.books.bank_transactions.list_all.return_value = [self.bank]

        entry = service.refresh()["entries"][0]

        self.assertFalse(entry["reviewable"])
        self.assertEqual(entry["creator"]["date"], "")
        self.assertEqual(
            entry["reason"],
            "No presented cheque detail matched cheque number and customer",
        )


if __name__ == "__main__":
    unittest.main()
