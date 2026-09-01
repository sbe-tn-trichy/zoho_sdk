import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
from pathlib import Path

from zoho.security import (
    mask_sensitive_value,
    sanitize_log_params,
    resolve_output_path,
)
from zoho.exceptions import (
    ZohoError,
    ZohoAuthError,
    ZohoBooksError,
    ZohoCliqError,
    ZohoSheetError,
)
from zoho.base_client import BaseZohoClient
from zoho.books.resources.purchases import Bills
from zoho.books.base import BaseResource
from zoho.cliq import ZohoCliqAPI
from zoho.sheet import ZohoSheetAPI


class TestSecurityAuditRemediation(unittest.TestCase):
    def test_mask_sensitive_value(self):
        self.assertEqual(mask_sensitive_value("33AAACP1234A1Z5"), "***A1Z5")
        self.assertEqual(mask_sensitive_value("50200012345678"), "***5678")
        self.assertEqual(mask_sensitive_value("+919876543210"), "***3210")
        self.assertEqual(mask_sensitive_value("1234"), "****")
        self.assertEqual(mask_sensitive_value("abc"), "****")
        self.assertEqual(mask_sensitive_value(""), "")
        self.assertEqual(mask_sensitive_value(None), "")

    def test_sanitize_log_params(self):
        params = {
            "page": 1,
            "per_page": 200,
            "status": "active",
            "gst_no": "33AAACP1234A1Z5",
            "email": "finance@sribharath.com",
            "authtoken": "secret_token_123456",
            "bank_account_number": "1094368000045308003",
        }
        sanitized = sanitize_log_params(params)
        self.assertEqual(sanitized["page"], 1)
        self.assertEqual(sanitized["per_page"], 200)
        self.assertEqual(sanitized["status"], "active")
        self.assertEqual(sanitized["gst_no"], "***A1Z5")
        self.assertEqual(sanitized["email"], "***.com")
        self.assertEqual(sanitized["authtoken"], "***3456")
        self.assertEqual(sanitized["bank_account_number"], "***8003")

    def test_strict_containment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Relative path inside base_dir is allowed
            safe = resolve_output_path("sub/report.xlsx", base_dir=tmpdir, strict_containment=True)
            self.assertTrue(safe.startswith(str(Path(tmpdir).resolve())))

            # Absolute path inside base_dir is allowed
            abs_inside = str(Path(tmpdir) / "inside.pdf")
            self.assertEqual(
                Path(resolve_output_path(abs_inside, base_dir=tmpdir, strict_containment=True)),
                Path(abs_inside).resolve(),
            )

            # Absolute path outside base_dir raises ValueError when strict_containment=True
            abs_outside = "/etc/passwd"
            with self.assertRaises(ValueError) as ctx:
                resolve_output_path(abs_outside, base_dir=tmpdir, strict_containment=True)
            self.assertIn("Strict containment violation", str(ctx.exception))


class TestStructuredErrors(unittest.TestCase):
    def test_zoho_error_structured_fields(self):
        err = ZohoError(
            "Something failed",
            status_code=400,
            error_code="INVALID_DATA",
            response_data={"field": "sku"},
            endpoint="items",
            retry_after=60
        )
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.error_code, "INVALID_DATA")
        self.assertEqual(err.response_data, {"field": "sku"})
        self.assertEqual(err.endpoint, "items")
        self.assertEqual(err.retry_after, 60)

    def test_base_client_sanitizes_html_error(self):
        client = BaseZohoClient(
            access_token="tok",
            domain="in",
            base_url="https://books.zoho.in/api/v3",
            service_name="books"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.reason = "Bad Gateway"
        mock_resp.text = "<html><body><h1>502 Bad Gateway</h1><p>Internal cloud gateway stack trace</p></body></html>"
        mock_resp.json.side_effect = Exception("Not JSON")

        with self.assertRaises(ZohoBooksError) as ctx:
            client._raise_for_status(mock_resp, endpoint="invoices")
        
        err = ctx.exception
        self.assertEqual(err.status_code, 502)
        self.assertNotIn("<h1>", str(err))
        self.assertIn("HTTP 502 (Bad Gateway)", str(err))

    @patch("requests.Session.request")
    def test_empty_refresh_token_preserves_existing_token(self, request):
        response = MagicMock(status_code=401)
        request.return_value = response
        client = BaseZohoClient(
            access_token="still-valid",
            domain="in",
            base_url="https://example.invalid",
            service_name="books",
            token_refresh_callback=lambda: "",
        )

        with self.assertRaises(ZohoAuthError):
            client.request("GET", "items")

        self.assertEqual(client.access_token, "still-valid")
        response.close.assert_called_once_with()


class TestUsabilityAndPerformance(unittest.TestCase):
    def test_bills_partial_update_succeeds(self):
        client = MagicMock()
        client.request.return_value = {"code": 0, "message": "success"}
        bills = Bills(client)

        # Partial update with only adjustment/notes must not trigger missing required fields
        res = bills.update("bill_123", {"notes": "Updated note", "adjustment": 10.0})
        client.request.assert_called_once_with(
            'PUT',
            'bills/bill_123',
            json={"notes": "Updated note", "adjustment": 10.0},
            params=None,
            files=None
        )

    def test_list_iter_generator(self):
        client = MagicMock()
        # Page 1 returns 2 records, has_more_page=True
        # Page 2 returns 1 record, has_more_page=False
        client.request.side_effect = [
            {
                "items": [{"item_id": "1"}, {"item_id": "2"}],
                "page_context": {"has_more_page": True}
            },
            {
                "items": [{"item_id": "3"}],
                "page_context": {"has_more_page": False}
            }
        ]
        res = BaseResource(client, "items")
        records = list(res.list_iter(per_page=2))
        self.assertEqual(len(records), 3)
        self.assertEqual([r["item_id"] for r in records], ["1", "2", "3"])
        self.assertEqual(client.request.call_count, 2)

    def test_cliq_raise_on_error(self):
        client = ZohoCliqAPI(access_token="tok", domain="in")
        with patch.object(client, "request", side_effect=Exception("Connection failed")):
            # Default raise_on_error=False returns None
            self.assertIsNone(client.send_notification("hello", raise_on_error=False))

            # raise_on_error=True raises
            with self.assertRaises(Exception):
                client.send_notification("hello", raise_on_error=True)

    def test_sheet_error_handling(self):
        client = ZohoSheetAPI(access_token="tok", domain="in")
        
        # Error 2884 returns empty list
        with patch.object(client, "request", return_value={"error_code": 2884, "error_message": "Empty sheet"}):
            self.assertEqual(client.get_rows("wb_1", "Sheet1"), [])

        # Non-2884 error raises ZohoSheetError
        with patch.object(client, "request", return_value={"error_code": 5000, "error_message": "Permission denied"}):
            with self.assertRaises(ZohoSheetError) as ctx:
                client.get_rows("wb_1", "Sheet1")
            self.assertEqual(ctx.exception.error_code, 5000)


if __name__ == "__main__":
    unittest.main()
