import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
from pathlib import Path

from zoho.security import sanitize_filename, resolve_output_path
from zoho.mail import ZohoMailAPI
from zoho.books.resources.sales import SalesOrders


class TestSecurityUtilities(unittest.TestCase):
    def test_sanitize_filename(self):
        # Basic name
        self.assertEqual(sanitize_filename("invoice.pdf"), "invoice.pdf")

        # Path traversal sequences
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("..\\..\\windows\\system32\\calc.exe"), "calc.exe")

        # Dangerous and control characters
        self.assertEqual(sanitize_filename("report<1>:v2?.pdf"), "report_1__v2_.pdf")
        self.assertEqual(sanitize_filename("bad\x00name.txt"), "bad_name.txt")

        # Empty, whitespace, dots
        self.assertEqual(sanitize_filename(""), "unnamed")
        self.assertEqual(sanitize_filename("."), "unnamed")
        self.assertEqual(sanitize_filename(".."), "unnamed")
        self.assertEqual(sanitize_filename("   "), "unnamed")
        self.assertEqual(sanitize_filename("report.pdf...", fallback="fallback.pdf"), "report.pdf")

    def test_resolve_output_path_relative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Safe relative path
            resolved = resolve_output_path("reports/monthly.xlsx", base_dir=tmpdir)
            expected = str((Path(tmpdir) / "reports" / "monthly.xlsx").resolve())
            self.assertEqual(resolved, expected)

            # Directory traversal attempt
            resolved_escape = resolve_output_path("../../etc/passwd", base_dir=tmpdir)
            self.assertTrue(resolved_escape.startswith(str(Path(tmpdir).resolve())))
            self.assertEqual(os.path.basename(resolved_escape), "passwd")

    def test_resolve_output_path_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_target = os.path.join(tmpdir, "direct.pdf")
            resolved = resolve_output_path(abs_target, base_dir="/other")
            self.assertEqual(resolved, str(Path(abs_target).resolve()))

    def test_resolve_output_path_strict_containment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Valid path inside base_dir with strict_containment=True
            valid_path = os.path.join(tmpdir, "safe_report.xlsx")
            self.assertEqual(
                resolve_output_path(valid_path, base_dir=tmpdir, strict_containment=True),
                str(Path(valid_path).resolve())
            )

            # Violation: absolute path outside base_dir
            with self.assertRaises(ValueError) as ctx:
                resolve_output_path("/etc/passwd", base_dir=tmpdir, strict_containment=True)
            self.assertIn("Strict containment violation", str(ctx.exception))

    def test_sanitize_log_params(self):
        from zoho.security import sanitize_log_params

        params = {
            "authtoken": "1000.abcd1234efgh5678",
            "email": "customer@example.com",
            "gstin": "33AAAAA0000A1Z5",
            "normal_param": "regular_value",
            "nested": {
                "password": "supersecretpassword",
                "page": 1
            }
        }
        sanitized = sanitize_log_params(params)
        self.assertEqual(sanitized["authtoken"], "***5678")
        self.assertEqual(sanitized["email"], "***.com")
        self.assertEqual(sanitized["gstin"], "***A1Z5")
        self.assertEqual(sanitized["normal_param"], "regular_value")
        self.assertEqual(sanitized["nested"]["password"], "***word")
        self.assertEqual(sanitized["nested"]["page"], 1)


class TestMailSecurity(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        from zoho.mail.resources.messages import Messages
        self.messages = Messages(self.client, "acc123")

    def test_resolve_download_path_traversal_neutralized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            malicious_name = "../../etc/cron.d/malicious"
            path = self.messages.resolve_download_path(tmpdir, malicious_name)
            
            # Path must be confined within tmpdir
            self.assertTrue(path.startswith(str(Path(tmpdir).resolve())))
            self.assertEqual(os.path.basename(path), "malicious")

    def test_download_folder_attachments_sanitizes_names(self):
        self.messages.list_iter = MagicMock(return_value=[
            {"messageId": "m1", "hasAttachment": "yes"}
        ])
        self.messages.get_attachments_info = MagicMock(return_value={
            "data": [{"attachmentId": "att1", "attachmentName": "../../../exploit.sh"}]
        })
        self.messages.get_attachment_content = MagicMock(return_value=b"echo pwned")

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self.messages.download_folder_attachments("f123", tmpdir)
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].startswith(str(Path(tmpdir).resolve())))
            self.assertEqual(os.path.basename(paths[0]), "exploit.sh")


class TestSalesOrdersSecurity(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.sales_orders = SalesOrders(self.client)

    def test_create_from_yaml_requires_customer_id(self):
        yaml_content = "inv:\n  no: '123'\n  date: '2026-01-01'\nitems:\n  - sku: 'ITEM-1'\n    qty: 1\n    rate: 100\n    name: 'Widget'\n"
        with self.assertRaises(ValueError) as ctx:
            self.sales_orders.create_from_yaml(yaml_content, customer_id="")
        self.assertIn("customer_id is required", str(ctx.exception))

    def test_create_from_yaml_missing_items_requires_default_accounts(self):
        yaml_content = "inv:\n  no: '123'\n  date: '2026-01-01'\nitems:\n  - sku: 'NEW-SKU'\n    qty: 1\n    rate: 100\n    name: 'Widget'\n"
        self.client.items.list.return_value = {"items": []}
        with self.assertRaises(ValueError) as ctx:
            self.sales_orders.create_from_yaml(
                yaml_content,
                customer_id="cust123",
                create_missing_items=True,
                default_accounts=None
            )
        self.assertIn("default_accounts", str(ctx.exception))


class TestMultiTierConfig(unittest.TestCase):
    def test_config_loader_hierarchy(self):
        from workflows.core.config import get_config

        # 1. Default when unset
        self.assertEqual(get_config("NON_EXISTENT_KEY_12345", default="fallback"), "fallback")

        # 2. Environment variable override
        with patch.dict(os.environ, {"TEST_CONFIG_KEY": "env_override_value"}):
            self.assertEqual(get_config("TEST_CONFIG_KEY"), "env_override_value")


if __name__ == "__main__":
    unittest.main()
