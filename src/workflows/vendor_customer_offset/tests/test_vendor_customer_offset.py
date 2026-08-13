import unittest
from unittest.mock import MagicMock

from workflows.vendor_customer_offset import (
    VendorCustomerOffsetConfig,
    run_vendor_customer_offset,
)


GSTIN = "33ABCDE1234F1Z5"


def _contacts(customer_outstanding=120, vendor_outstanding=80):
    return [
        {
            "contact_id": "customer-1",
            "contact_type": "customer",
            "gst_no": GSTIN,
            "currency_code": "INR",
            "outstanding_receivable_amount": customer_outstanding,
        },
        {
            "contact_id": "vendor-1",
            "contact_type": "vendor",
            "gst_no": GSTIN,
            "currency_code": "INR",
            "outstanding_payable_amount": vendor_outstanding,
        },
    ]


class TestVendorCustomerOffset(unittest.TestCase):
    def setUp(self):
        self.books = MagicMock()
        self.books.bank_accounts.list_all.return_value = [
            {"account_id": "bank-1", "account_name": "Vendor To Customer"}
        ]
        self.books.contacts.list_all.return_value = _contacts()
        self.books.invoices.list_all.return_value = [
            {"invoice_id": "invoice-2", "due_date": "2026-02-01", "balance": 50},
            {"invoice_id": "invoice-1", "due_date": "2026-01-01", "balance": 50},
        ]
        self.books.bills.list_all.return_value = [
            {
                "bill_id": "bill-1",
                "date": "2026-01-10",
                "due_date": "2026-01-15",
                "balance": 50,
            },
            {
                "bill_id": "bill-2",
                "date": "2026-02-10",
                "due_date": "2026-02-15",
                "balance": 50,
            },
        ]

    def test_dry_run_uses_lowest_outstanding_and_allocates_oldest_first(self):
        result = run_vendor_customer_offset(self.books)

        self.assertEqual(result["summary"]["planned"], 2)
        self.assertEqual(result["summary"]["planned_customer_payments"], 2)
        self.assertEqual(result["summary"]["planned_vendor_payments"], 2)
        self.assertEqual([item["amount"] for item in result["planned"]], [50.0, 30.0])
        self.assertEqual(
            [item["payment_date"] for item in result["planned"]],
            ["2026-01-10", "2026-02-10"],
        )
        self.assertEqual(
            result["planned"][0]["invoice_allocations"],
            [{"invoice_id": "invoice-1", "amount_applied": 50.0}],
        )
        self.assertEqual(
            result["planned"][1]["invoice_allocations"],
            [{"invoice_id": "invoice-2", "amount_applied": 30.0}],
        )
        self.books.customer_payments.create.assert_not_called()
        self.books.vendor_payments.create.assert_not_called()
        self.books.request.assert_not_called()

    def test_live_run_verifies_link_and_posts_both_payments(self):
        self.books.request.side_effect = Exception(
            'HTTP Error: 400 - {"code":3051,"message":"already linked"}'
        )
        self.books.customer_payments.create.side_effect = [
            {"payment": {"payment_id": "cp-1"}},
            {"payment": {"payment_id": "cp-2"}},
        ]
        self.books.vendor_payments.create.side_effect = [
            {"vendorpayment": {"payment_id": "vp-1"}},
            {"vendorpayment": {"payment_id": "vp-2"}},
        ]

        result = run_vendor_customer_offset(
            self.books,
            VendorCustomerOffsetConfig(dry_run=False),
        )

        self.assertEqual(result["summary"]["posted"], 2)
        self.assertEqual(result["summary"]["posted_customer_payments"], 2)
        self.assertEqual(result["summary"]["posted_vendor_payments"], 2)
        self.assertEqual(result["posted"][0]["link_status"], "already_linked")
        customer_payloads = [
            call.args[0] for call in self.books.customer_payments.create.call_args_list
        ]
        vendor_payloads = [
            call.args[0] for call in self.books.vendor_payments.create.call_args_list
        ]
        self.assertEqual([item["amount"] for item in customer_payloads], [50.0, 30.0])
        self.assertEqual(
            [item["date"] for item in customer_payloads],
            ["2026-01-10", "2026-02-10"],
        )
        self.assertEqual(
            [item["date"] for item in vendor_payloads],
            ["2026-01-10", "2026-02-10"],
        )
        self.assertEqual(vendor_payloads[0]["bills"], [{"bill_id": "bill-1", "amount_applied": 50.0}])
        self.assertEqual(vendor_payloads[1]["bills"], [{"bill_id": "bill-2", "amount_applied": 30.0}])
        self.assertTrue(all(len(item["reference_number"]) <= 50 for item in customer_payloads))

    def test_duplicate_gstin_is_skipped(self):
        self.books.contacts.list_all.return_value = _contacts() + [
            {
                "contact_id": "customer-2",
                "contact_type": "customer",
                "gst_no": GSTIN,
                "currency_code": "INR",
                "outstanding_receivable_amount": 20,
            }
        ]

        result = run_vendor_customer_offset(self.books)

        self.assertEqual(result["candidate_pairs"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "ambiguous_gstin")
        self.books.invoices.list_all.assert_not_called()

    def test_vendor_id_limits_the_run_to_one_vendor(self):
        result = run_vendor_customer_offset(
            self.books,
            VendorCustomerOffsetConfig(vendor_id="different-vendor"),
        )

        self.assertEqual(result["candidate_pairs"], 0)
        self.books.invoices.list_all.assert_not_called()

    def test_insufficient_documents_is_skipped(self):
        self.books.invoices.list_all.return_value = [
            {"invoice_id": "invoice-1", "balance": 70}
        ]

        result = run_vendor_customer_offset(self.books)

        self.assertEqual(result["skipped"][0]["reason"], "insufficient_open_documents")
        self.books.customer_payments.create.assert_not_called()

    def test_void_documents_are_not_allocated(self):
        self.books.invoices.list_all.return_value = [
            {"invoice_id": "void-invoice", "status": "void", "balance": 80},
            {"invoice_id": "open-invoice", "status": "overdue", "balance": 80},
        ]

        result = run_vendor_customer_offset(self.books)

        allocated_ids = {
            allocation["invoice_id"]
            for item in result["planned"]
            for allocation in item["invoice_allocations"]
        }
        self.assertEqual(allocated_ids, {"open-invoice"})

    def test_vendor_failure_rolls_back_customer_payment(self):
        self.books.request.side_effect = Exception(
            'HTTP Error: 400 - {"code":3051,"message":"already linked"}'
        )
        self.books.customer_payments.create.return_value = {
            "payment": {"payment_id": "cp-1"}
        }
        self.books.vendor_payments.create.side_effect = RuntimeError("vendor failure")

        result = run_vendor_customer_offset(
            self.books,
            VendorCustomerOffsetConfig(dry_run=False),
        )

        self.books.customer_payments.delete.assert_called_once_with("cp-1")
        self.assertEqual(result["failed"][0]["rollback"], "customer_payment_deleted")

    def test_missing_vendor_invoice_date_is_skipped(self):
        self.books.bills.list_all.return_value = [
            {"bill_id": "bill-1", "balance": 80}
        ]

        result = run_vendor_customer_offset(self.books)

        self.assertEqual(result["skipped"][0]["reason"], "missing_vendor_invoice_date")
        self.books.customer_payments.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
