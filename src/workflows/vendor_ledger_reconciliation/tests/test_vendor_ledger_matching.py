import unittest
from unittest.mock import MagicMock, patch

from workflows.vendor_ledger_reconciliation.matcher import (
    reconcile_vendor,
    reconcile_vendor_account,
)


class TestReconcileVendorAccount(unittest.TestCase):
    def setUp(self):
        self.books_client = MagicMock()
        self.vendor_id = "vendor_123"
        self.ledger_path = "dummy_ledger.xls"

    @patch("os.path.exists")
    @patch("workflows.vendor_ledger_reconciliation._reconciler.get_ledger_metadata")
    @patch("workflows.vendor_ledger_reconciliation._reconciler.clean_ledger_file")
    def test_reconcile_vendor_account(self, mock_clean, mock_metadata, mock_exists):
        mock_exists.return_value = True
        mock_metadata.return_value = {
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "party_name": "POLYCAB INDIA LIMITED",
            "opening_balance": 0.0
        }
        
        # Mock cleaned ledger entries (1 sales invoice, 1 receipt, 1 credit memo, 1 debit memo)
        mock_clean.return_value = [
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
            },
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
            {
                "account_no": "108738",
                "account_name": "LTG-BHARATH DISTRIBUTORS",
                "date": "2026-01-04",
                "document_type": "Credit Memo",
                "transaction_no": "VC-111",
                "transaction_reference": "",
                "debit_amount": 0.0,
                "credit_amount": 100.0,
                "closing_balance": -110072.46
            },
            {
                "account_no": "108738",
                "account_name": "LTG-BHARATH DISTRIBUTORS",
                "date": "2026-01-05",
                "document_type": "Debit Memo",
                "transaction_no": "DB-111",
                "transaction_reference": "",
                "debit_amount": 50.0,
                "credit_amount": 0.0,
                "closing_balance": -110022.46
            }
        ]
        
        # Mock Zoho Bills (1 matching bill, 1 unmatched bill, 1 negative bill for debit memo)
        zoho_bills = [
            {
                "bill_id": "bill_01",
                "date": "2026-01-02",
                "bill_number": "2601238365",
                "reference_number": "",
                "amount": "314189.27",
                "total": "314189.27"
            },
            {
                "bill_id": "bill_02",
                "date": "2026-01-15",
                "bill_number": "BILL-999",
                "reference_number": "",
                "amount": "12345.00",
                "total": "12345.00"
            },
            {
                "bill_id": "bill_03",
                "date": "2026-01-05",
                "bill_number": "DB-111",
                "reference_number": "",
                "amount": "-50.00",
                "total": "-50.00"
            }
        ]
        self.books_client.bills.list_all.return_value = zoho_bills
        
        # Mock Zoho Vendor Payments (1 matching payment, 1 unmatched payment)
        zoho_payments = [
            {
                "payment_id": "pay_01",
                "date": "2026-01-03",
                "amount": "541000.00",
                "reference_number": "NBJ4RH6RTKHVQZTP"
            },
            {
                "payment_id": "pay_02",
                "date": "2026-01-20",
                "amount": "9999.00",
                "reference_number": "REF-999"
            }
        ]
        self.books_client.vendor_payments.list_all.return_value = zoho_payments
        
        # Mock the typed SDK Vendor Credits resource.
        self.books_client.vendor_credits.list_all.return_value = [
            {
                "vendor_credit_id": "vc_01",
                "date": "2026-01-04",
                "vendor_credit_number": "VC-111",
                "total": "100.00",
            }
        ]
        
        results = reconcile_vendor_account(
            books_client=self.books_client,
            vendor_id=self.vendor_id,
            vendor_ledger_path=self.ledger_path,
            date_tolerance_days=7,
            amount_tolerance=0.0
        )
        
        # Verify calls
        mock_clean.assert_called_once_with(self.ledger_path)
        self.books_client.bills.list_all.assert_called_once_with(params={"vendor_id": self.vendor_id, "from_date": "2026-01-01", "to_date": "2026-03-31"})
        self.books_client.vendor_payments.list_all.assert_called_once_with(params={"vendor_id": self.vendor_id, "from_date": "2026-01-01", "to_date": "2026-03-31"})
        
        # Verify Sales Invoice matches/unmatched
        sales_inv = results["sales_invoice"]
        self.assertEqual(len(sales_inv["matches"]), 1)
        self.assertEqual(sales_inv["matches"][0][0]["bill_id"], "bill_01")
        self.assertEqual(sales_inv["matches"][0][1]["transaction_no"], "2601238365")
        self.assertEqual(len(sales_inv["unmatched_books"]), 1)
        self.assertEqual(sales_inv["unmatched_books"][0]["bill_id"], "bill_02")
        self.assertEqual(len(sales_inv["unmatched_ledger"]), 0)
        
        # Verify Receipt matches/unmatched
        receipt = results["receipt"]
        self.assertEqual(len(receipt["matches"]), 1)
        self.assertEqual(receipt["matches"][0][0]["payment_id"], "pay_01")
        self.assertEqual(receipt["matches"][0][1]["transaction_no"], "NBJ4RH6RTKHVQZTP")
        self.assertEqual(len(receipt["unmatched_books"]), 1)
        self.assertEqual(receipt["unmatched_books"][0]["payment_id"], "pay_02")
        self.assertEqual(len(receipt["unmatched_ledger"]), 0)

        # Verify Credit Memo matches/unmatched
        credit_memo = results["credit_memo"]
        self.assertEqual(len(credit_memo["matches"]), 1)
        self.assertEqual(credit_memo["matches"][0][0]["vendor_credit_id"], "vc_01")
        self.assertEqual(credit_memo["matches"][0][1]["transaction_no"], "VC-111")
        self.assertEqual(len(credit_memo["unmatched_books"]), 0)
        self.assertEqual(len(credit_memo["unmatched_ledger"]), 0)

        # Verify Debit Memo matches/unmatched
        debit_memo = results["debit_memo"]
        self.assertEqual(len(debit_memo["matches"]), 1)
        self.assertEqual(debit_memo["matches"][0][0]["bill_id"], "bill_03")
        self.assertEqual(debit_memo["matches"][0][1]["transaction_no"], "DB-111")
        self.assertEqual(len(debit_memo["unmatched_books"]), 0)
        self.assertEqual(len(debit_memo["unmatched_ledger"]), 0)

class TestReconcileVendor(unittest.TestCase):
    def setUp(self):
        self.books_client = MagicMock()
        self.ledger_path_polycab = "input_files/polycab/ledger/277498_Statement.xls"
        self.ledger_path_zeiss = "input_files/zeiss/Statement.csv"
        self.ledger_path_unknown = "input_files/unknown/ledger.xls"

    @patch("workflows.vendor_ledger_reconciliation._reconciler.reconcile_vendor_account")
    @patch("workflows.core.auth.get_books_client")
    def test_reconcile_vendor_with_all_explicit_params(self, mock_get_client, mock_reconcile_account):
        mock_reconcile_account.return_value = {"status": "success"}

        res = reconcile_vendor(
            vendor_ledger_path=self.ledger_path_polycab,
            vendor_id="vendor_explicit",
            date_tolerance_days=10,
            amount_tolerance=0.01,
            books_client=self.books_client
        )

        mock_reconcile_account.assert_called_once_with(
            books_client=self.books_client,
            vendor_id="vendor_explicit",
            vendor_ledger_path=self.ledger_path_polycab,
            date_tolerance_days=10,
            amount_tolerance=0.01
        )
        self.assertEqual(res, {"status": "success"})
        mock_get_client.assert_not_called()

    @patch("workflows.vendor_ledger_reconciliation._reconciler.reconcile_vendor_account")
    @patch("workflows.core.auth.get_books_client")
    def test_reconcile_vendor_auto_detect_polycab(self, mock_get_client, mock_reconcile_account):
        from workflows.core.config import Config
        mock_reconcile_account.return_value = {"status": "success"}
        mock_get_client.return_value = self.books_client

        res = reconcile_vendor(
            vendor_ledger_path=self.ledger_path_polycab
        )

        mock_reconcile_account.assert_called_once_with(
            books_client=self.books_client,
            vendor_id=Config.POLYCAB_VENDOR_ID,
            vendor_ledger_path=self.ledger_path_polycab,
            date_tolerance_days=7,
            amount_tolerance=0.0
        )
        mock_get_client.assert_called_once()
        self.assertEqual(res, {"status": "success"})

    @patch("workflows.vendor_ledger_reconciliation._reconciler.reconcile_vendor_account")
    @patch("workflows.core.auth.get_books_client")
    def test_reconcile_vendor_auto_detect_zeiss(self, mock_get_client, mock_reconcile_account):
        from workflows.core.config import Config
        mock_reconcile_account.return_value = {"status": "success"}
        mock_get_client.return_value = self.books_client

        res = reconcile_vendor(
            vendor_ledger_path=self.ledger_path_zeiss,
            books_client=self.books_client
        )

        mock_reconcile_account.assert_called_once_with(
            books_client=self.books_client,
            vendor_id=Config.ZEISS_VENDOR_ID,
            vendor_ledger_path=self.ledger_path_zeiss,
            date_tolerance_days=7,
            amount_tolerance=0.0
        )
        mock_get_client.assert_not_called()
        self.assertEqual(res, {"status": "success"})

    def test_reconcile_vendor_auto_detect_unknown_fails(self):
        with self.assertRaises(ValueError):
            reconcile_vendor(
                vendor_ledger_path=self.ledger_path_unknown,
                books_client=self.books_client
            )
