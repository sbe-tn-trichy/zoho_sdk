import unittest
from unittest.mock import MagicMock
from datetime import date
from workflows.bank_vendor_ledger_matching.matcher import (
    get_bank_reference,
    parse_date,
    get_abs_amount,
    ref_match,
    match_ledger_entries
)

class TestLedgerMatcherUtils(unittest.TestCase):
    def test_icici_upi_reference_comes_from_description(self):
        transaction = {
            "reference_number": "S78528277",
            "description": "UPI/622494425255/UPI/customer@bank/BANK/AXI123",
        }

        self.assertEqual(
            get_bank_reference(transaction, "1094368000056644467"),
            "622494425255",
        )

    def test_icici_non_upi_and_other_banks_keep_zoho_reference(self):
        transaction = {
            "reference_number": "S78528277",
            "description": "NEFT/SOME/OTHER/FORMAT",
        }

        self.assertEqual(
            get_bank_reference(transaction, "1094368000056644467"),
            "S78528277",
        )
        self.assertEqual(
            get_bank_reference(
                {
                    "reference_number": "BANK-REF",
                    "description": "UPI/622494425255/UPI/customer@bank/BANK/AXI123",
                },
                "another-bank",
            ),
            "BANK-REF",
        )

    def test_parse_date(self):
        self.assertEqual(parse_date("2026-06-14"), date(2026, 6, 14))
        self.assertEqual(parse_date("2026-06-14T11:24:20Z"), date(2026, 6, 14))
        self.assertEqual(parse_date(date(2026, 6, 14)), date(2026, 6, 14))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("invalid-date"))

    def test_get_abs_amount(self):
        self.assertEqual(get_abs_amount({"amount": "-150.50"}), 150.50)
        self.assertEqual(get_abs_amount({"amount": 150.50}), 150.50)
        self.assertEqual(get_abs_amount({"amount": "abc"}), 0.0)

    def test_ref_match(self):
        self.assertTrue(ref_match("REF123", "  ref123  "))
        self.assertFalse(ref_match("REF123", ""))
        self.assertFalse(ref_match("", ""))
        self.assertFalse(ref_match("REF123", "REF456"))

class TestMatchLedgerEntries(unittest.TestCase):
    def setUp(self):
        self.books_client = MagicMock()
        self.bank_account_id = "bank_123"
        self.vendor_id = "vendor_456"

    def test_match_ledger_entries(self):
        # Setup mock bank transactions (withdrawals/debits)
        bank_transactions = [
            # Exact Match 1
            {
                "transaction_id": "tx_01",
                "date": "2026-06-10",
                "amount": "-1000.00",
                "reference_number": "REF-001",
                "debit_or_credit": "debit"
            },
            # Strong Match 2 (no ref match, but exact amount and within date tolerance)
            {
                "transaction_id": "tx_02",
                "date": "2026-06-11",
                "amount": "-500.00",
                "reference_number": "REF-002",
                "debit_or_credit": "debit"
            },
            # Weak Match 3 (amount off by 5.0, but within tolerance of 10.0, and within date tolerance)
            {
                "transaction_id": "tx_03",
                "date": "2026-06-12",
                "amount": "-255.00",
                "reference_number": "REF-003",
                "debit_or_credit": "debit"
            },
            # Unmatched Bank Transaction
            {
                "transaction_id": "tx_04",
                "date": "2026-06-13",
                "amount": "-1500.00",
                "reference_number": "REF-004",
                "debit_or_credit": "debit"
            },
            # Deposit (should be ignored because it is not a withdrawal/outflow)
            {
                "transaction_id": "tx_05",
                "date": "2026-06-10",
                "amount": "1000.00",
                "debit_or_credit": "credit"
            }
        ]

        # Setup mock vendor payments
        vendor_payments = [
            # Exact Match with tx_01
            {
                "payment_id": "vp_01",
                "date": "2026-06-10",
                "amount": "1000.00",
                "reference_number": "REF-001"
            },
            # Strong Match with tx_02 (reference missing on one side)
            {
                "payment_id": "vp_02",
                "date": "2026-06-12",
                "amount": "500.00",
                "reference_number": ""
            },
            # Weak Match with tx_03 (amount is 250.00, difference of 5.00)
            {
                "payment_id": "vp_03",
                "date": "2026-06-11",
                "amount": "250.00",
                "reference_number": "REF-003"
            },
            # Unmatched Vendor Payment
            {
                "payment_id": "vp_04",
                "date": "2026-06-10",
                "amount": "75.00",
                "reference_number": "REF-009"
            }
        ]

        self.books_client.bank_transactions.list_all.return_value = bank_transactions
        self.books_client.vendor_payments.list_all.return_value = vendor_payments

        # Match with 10.0 amount tolerance, 7 days date tolerance
        results = match_ledger_entries(
            books_client=self.books_client,
            bank_account_id=self.bank_account_id,
            vendor_id=self.vendor_id,
            date_tolerance_days=7,
            amount_tolerance=10.0
        )

        self.books_client.bank_transactions.list_all.assert_called_once_with(params={"account_id": self.bank_account_id})
        self.books_client.vendor_payments.list_all.assert_called_once_with(params={"vendor_id": self.vendor_id})

        # Verify exact matches
        self.assertEqual(len(results["exact_matches"]), 1)
        self.assertEqual(results["exact_matches"][0][0]["transaction_id"], "tx_01")
        self.assertEqual(results["exact_matches"][0][1]["payment_id"], "vp_01")

        # Verify strong matches
        self.assertEqual(len(results["strong_matches"]), 1)
        self.assertEqual(results["strong_matches"][0][0]["transaction_id"], "tx_02")
        self.assertEqual(results["strong_matches"][0][1]["payment_id"], "vp_02")

        # Verify weak matches
        self.assertEqual(len(results["weak_matches"]), 1)
        self.assertEqual(results["weak_matches"][0][0]["transaction_id"], "tx_03")
        self.assertEqual(results["weak_matches"][0][1]["payment_id"], "vp_03")

        # Verify unmatched bank transactions (tx_04 remains, deposit tx_05 is excluded entirely)
        self.assertEqual(len(results["unmatched_bank_transactions"]), 1)
        self.assertEqual(results["unmatched_bank_transactions"][0]["transaction_id"], "tx_04")

        # Verify unmatched vendor payments (vp_04 remains)
        self.assertEqual(len(results["unmatched_vendor_payments"]), 1)
        self.assertEqual(results["unmatched_vendor_payments"][0]["payment_id"], "vp_04")

    def test_icici_upi_description_reference_is_used_for_exact_match(self):
        self.books_client.bank_transactions.list_all.return_value = [{
            "transaction_id": "tx_icici",
            "date": "2026-08-12",
            "amount": "-1000.00",
            "reference_number": "S78528277",
            "description": "UPI/622494425255/UPI/customer@bank/BANK/AXI123",
            "debit_or_credit": "debit",
        }]
        self.books_client.vendor_payments.list_all.return_value = [{
            "payment_id": "vp_icici",
            "date": "2026-08-12",
            "amount": "1000.00",
            "reference_number": "622494425255",
        }]

        results = match_ledger_entries(
            books_client=self.books_client,
            bank_account_id="1094368000056644467",
            vendor_id=self.vendor_id,
        )

        self.assertEqual(len(results["exact_matches"]), 1)
        self.assertEqual(results["strong_matches"], [])

    def test_duplicate_external_ids_do_not_hide_unmatched_rows(self):
        self.books_client.bank_transactions.list_all.return_value = [
            {"transaction_id": "duplicate", "date": "2026-01-01", "amount": "-100", "reference_number": "A", "debit_or_credit": "debit"},
            {"transaction_id": "duplicate", "date": "2026-01-02", "amount": "-200", "reference_number": "B", "debit_or_credit": "debit"},
        ]
        self.books_client.vendor_payments.list_all.return_value = [
            {"payment_id": "payment", "date": "2026-01-01", "amount": "100", "reference_number": "A"}
        ]

        results = match_ledger_entries(
            self.books_client, self.bank_account_id, self.vendor_id
        )

        self.assertEqual(len(results["exact_matches"]), 1)
        self.assertEqual(results["unmatched_bank_transactions"][0]["amount"], "-200")

    def test_ambiguous_equal_amount_candidates_are_not_greedily_matched(self):
        self.books_client.bank_transactions.list_all.return_value = [
            {"transaction_id": "b1", "date": "2026-01-01", "amount": "-100", "debit_or_credit": "debit"},
            {"transaction_id": "b2", "date": "2026-01-04", "amount": "-100", "debit_or_credit": "debit"},
        ]
        payments = [
            {"payment_id": "p4", "date": "2026-01-04", "amount": "100"},
            {"payment_id": "p1", "date": "2026-01-01", "amount": "100"},
        ]
        self.books_client.vendor_payments.list_all.return_value = payments

        first = match_ledger_entries(
            self.books_client, self.bank_account_id, self.vendor_id,
            date_tolerance_days=3,
        )
        self.books_client.vendor_payments.list_all.return_value = list(reversed(payments))
        second = match_ledger_entries(
            self.books_client, self.bank_account_id, self.vendor_id,
            date_tolerance_days=3,
        )

        self.assertEqual(first["strong_matches"], [])
        self.assertEqual(second["strong_matches"], [])
        self.assertEqual(len(first["ambiguous_matches"]), 2)
        self.assertEqual(len(second["ambiguous_matches"]), 2)

    def test_partial_date_filter_is_applied(self):
        self.books_client.bank_transactions.list_all.return_value = []
        self.books_client.vendor_payments.list_all.return_value = []

        match_ledger_entries(
            self.books_client,
            self.bank_account_id,
            self.vendor_id,
            start_date=date(2026, 1, 10),
            date_tolerance_days=2,
        )

        self.books_client.bank_transactions.list_all.assert_called_once_with(
            params={"account_id": self.bank_account_id, "from_date": "2026-01-08"}
        )
        self.books_client.vendor_payments.list_all.assert_called_once_with(
            params={"vendor_id": self.vendor_id, "from_date": "2026-01-10"}
        )

from unittest.mock import patch
from workflows.bank_vendor_ledger_matching.matcher import (
    match_bank_with_vendor_ledger
)

class TestMatchBankWithVendorLedger(unittest.TestCase):
    def setUp(self):
        self.books_client = MagicMock()
        self.bank_account_id = "bank_123"
        self.ledger_path = "dummy_ledger.xls"

    @patch("os.path.exists")
    @patch("workflows.bank_vendor_ledger_matching._matcher.get_ledger_metadata")
    @patch("workflows.bank_vendor_ledger_matching._matcher.clean_ledger_file")
    def test_match_bank_with_vendor_ledger(self, mock_clean, mock_metadata, mock_exists):
        mock_exists.return_value = True
        mock_metadata.return_value = {
            "start_date": "2026-01-01",
            "end_date": "2026-01-10",
        }
        
        # Setup mock bank transactions (withdrawals)
        bank_transactions = [
            {
                "transaction_id": "tx_01",
                "date": "2026-01-02",
                "amount": "-314189.27",
                "reference_number": "TN721S2526104838",
                "debit_or_credit": "debit"
            },
            {
                "transaction_id": "tx_02",
                "date": "2026-01-03",
                "amount": "-541000.00",
                "cheque_number": "NBJ4RH6RTKHVQZTP",
                "debit_or_credit": "debit"
            }
        ]
        self.books_client.bank_transactions.list_all.return_value = bank_transactions
        
        # Setup mock cleaned ledger entries
        mock_clean.return_value = [
            # Receipt (Credit) -> Matches tx_02 exactly by ref (transaction_no is check ref) and amount and date
            {
                "account_no": "108738",
                "account_name": "LTG-BHARATH DISTRIBUTORS",
                "date": "2026-01-03",
                "document_type": "Receipt",
                "transaction_no": "NBJ4RH6RTKHVQZTP",
                "transaction_reference": "",
                "debit_amount": 0.0,
                "credit_amount": 541000.0,
                "closing_balance": -109972.46
            },
            # Sales Invoice -> Ignored since debit_amount > 0 and credit_amount == 0 and not Receipt
            {
                "account_no": "109461",
                "account_name": "FAN-BHARATH DISTRIBUTORS",
                "date": "2026-01-02",
                "document_type": "Sales Invoice",
                "transaction_no": "2601238365",
                "transaction_reference": "TN721S2526104838",
                "debit_amount": 314189.27,
                "credit_amount": 0.0,
                "closing_balance": -40884.44
            }
        ]
        
        results = match_bank_with_vendor_ledger(
            books_client=self.books_client,
            bank_account_id=self.bank_account_id,
            vendor_ledger_path=self.ledger_path,
            date_tolerance_days=7,
            amount_tolerance=0.0
        )
        
        self.books_client.bank_transactions.list_all.assert_called_once_with(params={
            "account_id": self.bank_account_id,
            "from_date": "2025-12-25",
            "to_date": "2026-01-17"
        })
        mock_clean.assert_called_once_with(self.ledger_path)
        
        # tx_02 matches the ledger Receipt
        self.assertEqual(len(results["exact_matches"]), 1)
        self.assertEqual(results["exact_matches"][0][0]["transaction_id"], "tx_02")
        self.assertEqual(results["exact_matches"][0][1]["transaction_no"], "NBJ4RH6RTKHVQZTP")
        
        # tx_01 has no matching credit receipt in Polycab's ledger (only a sales invoice, which we skip)
        self.assertEqual(len(results["unmatched_bank_transactions"]), 1)
        self.assertEqual(results["unmatched_bank_transactions"][0]["transaction_id"], "tx_01")
        
        # No unmatched ledger receipts since the only one got matched
        self.assertEqual(len(results["unmatched_ledger_receipts"]), 0)
