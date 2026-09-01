import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from zoho.base_client import BaseZohoClient
from zoho.downloads import write_response_to_file
from zoho.books import ZohoBooksAPI
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

    def test_concrete_books_client_forwards_stream_and_timeout(self):
        client = ZohoBooksAPI("token", "org-1")
        response = MagicMock(status_code=200)
        client.session.request = MagicMock(return_value=response)

        self.assertIs(
            client.request("GET", "reports/test", stream=True, timeout=12),
            response,
        )
        client.session.request.assert_called_once_with(
            method="GET",
            url="https://www.zohoapis.com/books/v3/reports/test",
            headers={
                "Authorization": "Zoho-oauthtoken token",
                "Content-Type": "application/json",
            },
            params={"organization_id": "org-1"},
            json=None,
            files=None,
            timeout=12,
            stream=True,
        )

    def test_stream_callback_does_not_materialize_response_body(self):
        callback = MagicMock()
        client = BaseZohoClient(
            access_token="token",
            domain="com",
            base_url="https://example.invalid",
            service_name="books",
            on_request_completed=callback,
        )

        class StreamingResponse:
            status_code = 200
            headers = {}

            @property
            def text(self):
                raise AssertionError("streaming response body was materialized")

        response = StreamingResponse()
        client.session.request = MagicMock(return_value=response)
        self.assertIs(client.request("GET", "download", stream=True), response)
        callback.assert_called_once_with("GET", "download", None, 200, None)


class TestDownloadWriter(unittest.TestCase):
    def test_unsupported_response_is_rejected_and_closed(self):
        response = MagicMock(spec=[])
        response.close = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = os.path.join(tmpdir, "download.bin")
            with self.assertRaises(TypeError):
                write_response_to_file(response, destination)
            self.assertFalse(os.path.exists(destination))
        response.close.assert_called_once()

    def test_interrupted_stream_propagates_and_closes(self):
        response = MagicMock()

        def chunks(chunk_size):
            yield b"partial"
            raise OSError("connection lost")

        response.iter_content.side_effect = chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = os.path.join(tmpdir, "download.bin")
            with self.assertRaisesRegex(OSError, "connection lost"):
                write_response_to_file(response, destination)
        response.close.assert_called_once()


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


class TestStreamingAndPagination(unittest.TestCase):
    def test_list_iter_yields_item_by_item(self):
        from zoho.books.base import BaseResource
        client = MagicMock()
        resource = BaseResource(client, "invoices")

        # Mock 2 pages of 2 items each
        client.request.side_effect = [
            {
                "invoices": [{"invoice_id": "inv_1"}, {"invoice_id": "inv_2"}],
                "page_context": {"has_more_page": True}
            },
            {
                "invoices": [{"invoice_id": "inv_3"}],
                "page_context": {"has_more_page": False}
            }
        ]

        items = list(resource.list_iter(per_page=2))
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["invoice_id"], "inv_1")
        self.assertEqual(items[2]["invoice_id"], "inv_3")
        self.assertEqual(client.request.call_count, 2)

    def test_workdrive_download_closes_stream(self):
        from zoho.wd.resources.files import Files
        client = MagicMock()
        client.domain = "com"
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        client.request.return_value = mock_response

        files = Files(client)
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "file.txt")
            files.download("file_123", target)
            mock_response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
