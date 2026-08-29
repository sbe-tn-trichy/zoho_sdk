import unittest
from unittest.mock import MagicMock

from workflows.duplicate_payment_check import DuplicatePaymentChecker


class TestDuplicatePaymentChecker(unittest.TestCase):
    def setUp(self):
        self.books = MagicMock()
        self.checker = DuplicatePaymentChecker(self.books)

    def test_finds_only_exact_customer_date_amount_duplicates(self):
        payments = [
            {"payment_id": "p1", "customer_id": "c1", "customer_name": "Acme", "date": "2026-08-01", "amount": 100},
            {"payment_id": "p2", "customer_id": "c1", "customer_name": "Acme", "date": "2026-08-01", "amount": "100.00"},
            {"payment_id": "p3", "customer_id": "c2", "customer_name": "Acme", "date": "2026-08-01", "amount": 100},
            {"payment_id": "p4", "customer_id": "c1", "customer_name": "Acme", "date": "2026-08-02", "amount": 100},
            {"payment_id": "p5", "customer_id": "c1", "customer_name": "Acme", "date": "2026-08-01", "amount": 101},
        ]

        result = self.checker.check(payments)

        self.assertEqual(result["duplicate_group_count"], 1)
        self.assertEqual(result["duplicate_payment_count"], 2)
        self.assertEqual([p["payment_id"] for p in result["duplicate_groups"][0]["payments"]], ["p1", "p2"])

    def test_retrieves_detail_when_list_item_omits_customer_id(self):
        self.books.customer_payments.get.return_value = {
            "payment": {"customer_id": "c1", "customer_name": "Acme"}
        }
        payments = [
            {"payment_id": "p1", "date": "2026-08-01", "amount": 100},
            {"payment_id": "p2", "customer_id": "c1", "date": "2026-08-01", "amount": 100},
        ]

        result = self.checker.check(payments)

        self.books.customer_payments.get.assert_called_once_with("p1")
        self.assertEqual(result["duplicate_group_count"], 1)

    def test_run_paginates_and_applies_local_date_range(self):
        self.books.customer_payments.list_all.return_value = [
            {"payment_id": "old", "customer_id": "c1", "date": "2026-07-31", "amount": 100},
            {"payment_id": "p1", "customer_id": "c1", "date": "2026-08-01", "amount": 100},
            {"payment_id": "p2", "customer_id": "c1", "date": "2026-08-01", "amount": 100},
        ]

        result = self.checker.run(customer_id="c1", from_date="2026-08-01", to_date="2026-08-31")

        self.books.customer_payments.list_all.assert_called_once_with(
            params={"customer_id": "c1", "date_start": "2026-08-01", "date_end": "2026-08-31"}
        )
        self.assertEqual(result["payments_considered"], 2)
        self.assertEqual(result["duplicate_group_count"], 1)


    def test_rejects_inverted_date_range(self):
        with self.assertRaisesRegex(ValueError, "cannot be later"):
            self.checker.run(from_date="2026-08-02", to_date="2026-08-01")


if __name__ == "__main__":
    unittest.main()
