import unittest
from unittest.mock import patch, MagicMock
from zoho.base_client import BaseZohoClient
from zoho.books.resources.sales import SalesOrders
from zoho.books.resources.gst import GST
from workflows.duplicate_payment_check import DuplicatePaymentChecker


class TestBaseClientPerformance(unittest.TestCase):
    def test_session_instantiation_and_close(self):
        client = BaseZohoClient(
            access_token="test_token",
            domain="com",
            base_url="https://books.zoho.com/api/v3",
            service_name="books"
        )
        self.assertIsNotNone(client.session)
        
        # Test context manager support
        with client as c:
            self.assertIsNotNone(c.session)

    def test_universal_default_timeout(self):
        for service in ["books", "wd", "mail", "creator", "sheet", "cliq", "analytics"]:
            client = BaseZohoClient(
                access_token="test_token",
                domain="com",
                base_url="https://api.zoho.com",
                service_name=service,
                default_timeout=45
            )
            self.assertEqual(client.default_timeout, 45)


class TestSalesOrdersSKUCaching(unittest.TestCase):
    def test_sku_caching_avoids_duplicate_http_queries(self):
        client = MagicMock()
        client.items.list.return_value = {
            "items": [{"item_id": "item_123", "name": "Standard Fan"}]
        }
        client.sales_orders = SalesOrders(client)

        yaml_content = """
inv:
  no: '1001'
  date: '2026-01-15'
items:
  - sku: 'FAN-01'
    name: 'Standard Fan'
    qty: 2
    rate: 1500
  - sku: 'FAN-01'
    name: 'Standard Fan'
    qty: 3
    rate: 1500
"""
        client.sales_orders.create = MagicMock(return_value={"salesorder": {"salesorder_id": "so_1"}})
        res = client.sales_orders.create_from_yaml(yaml_content, customer_id="cust_999")

        # items.list should only be called ONCE for 'FAN-01' even though it appeared twice in line items
        client.items.list.assert_called_once_with(params={"sku": "FAN-01"})
        self.assertIn("salesorder", res)


class TestGSTRatePacing(unittest.TestCase):
    @patch("time.sleep")
    def test_gst_fetch_details_retries_on_429(self, mock_sleep):
        client = MagicMock()
        gst = GST(client)

        mock_module = MagicMock()
        # Fail with 429 on first call, succeed on second call
        mock_module.get.side_effect = [
            Exception("HTTP 429: Too Many Requests"),
            {"invoice": {"invoice_id": "inv_1", "total": 1000}}
        ]

        docs = [{"invoice_id": "inv_1"}]
        details = gst._fetch_details_concurrently(mock_module, docs, "invoice_id", "invoice")

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["invoice_id"], "inv_1")
        mock_sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
