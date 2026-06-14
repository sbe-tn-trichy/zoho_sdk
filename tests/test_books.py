import unittest
from unittest.mock import patch, MagicMock
from zoho.books import ZohoBooksAPI, ZohoBooksError
from zoho.books.base import BaseResource
from zoho.books.resources.customer_validator import CustomerValidator
from zoho.books.resources.gst import GST, parse_doc_number
from zoho.books.resources.projects import Projects, TimeEntries

class TestZohoBooksAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.org_id = "org123"
        self.client = ZohoBooksAPI(access_token=self.access_token, organization_id=self.org_id, domain="com")

    def test_init_success(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.organization_id, self.org_id)
        self.assertEqual(self.client.base_url, "https://www.zohoapis.com/books/v3")

    def test_init_missing_org(self):
        with self.assertRaises(ValueError):
            ZohoBooksAPI(access_token=self.access_token, organization_id="")

    @patch("requests.request")
    def test_request_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_request.return_value = mock_response

        res = self.client.request("GET", "invoices")
        self.assertEqual(res, {"status": "ok"})
        mock_request.assert_called_once_with(
            method="GET",
            url="https://www.zohoapis.com/books/v3/invoices",
            headers={
                "Authorization": "Zoho-oauthtoken fake_access_token",
                "Content-Type": "application/json"
            },
            params={"organization_id": "org123"},
            json=None,
            files=None,
            timeout=30
        )

    @patch("requests.request")
    def test_request_token_refresh(self, mock_request):
        token_callback = MagicMock(return_value="new_token")
        client = ZohoBooksAPI(access_token="old_token", organization_id="org123", token_refresh_callback=token_callback)
        
        mock_response1 = MagicMock()
        mock_response1.status_code = 401
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.headers = {"Content-Type": "application/json"}
        mock_response2.text = '{"status": "ok"}'
        mock_response2.json.return_value = {"status": "ok"}
        
        mock_request.side_effect = [mock_response1, mock_response2]

        res = client.request("GET", "invoices")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(client.access_token, "new_token")
        self.assertEqual(mock_request.call_count, 2)


class TestBooksBaseResource(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.resource = BaseResource(self.client, "testresource")
        self.resource.required_fields = ["name", "code"]
        self.resource.defaults = {"status": "active"}
        self.resource.line_item_required_fields = ["item_id", "qty"]
        self.resource.line_item_defaults = {"rate": 0.0}

    def test_prepare_payload_create_success(self):
        data = {
            "name": "Widget",
            "code": "W1",
            "line_items": [{"item_id": "i1", "qty": 5}]
        }
        payload = self.resource._prepare_payload(data, check_required=True)
        self.assertEqual(payload["name"], "Widget")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["line_items"][0]["rate"], 0.0)

    def test_prepare_payload_create_missing_field(self):
        data = {"name": "Widget"}
        with self.assertRaises(ZohoBooksError):
            self.resource._prepare_payload(data, check_required=True)

    def test_prepare_payload_update(self):
        data = {"name": "Updated Widget"}
        payload = self.resource._prepare_payload(data, check_required=False)
        self.assertEqual(payload, data)

    def test_list(self):
        self.resource.list(params={"custom": "val"})
        self.client.request.assert_called_once_with('GET', 'testresource', params={"custom": "val"})

    def test_list_all(self):
        page1 = {"testresource": [{"id": "r1"}], "page_context": {"has_more_page": True}}
        page2 = {"testresource": [{"id": "r2"}], "page_context": {"has_more_page": False}}
        self.client.request.side_effect = [page1, page2]

        records = self.resource.list_all()
        self.assertEqual(records, [{"id": "r1"}, {"id": "r2"}])
        self.assertEqual(self.client.request.call_count, 2)

    def test_get(self):
        self.resource.get("r123", params={"p": "1"})
        self.client.request.assert_called_once_with('GET', 'testresource/r123', params={"p": "1"})

    def test_create(self):
        data = {"name": "Widget", "code": "W1"}
        self.resource.create(data)
        self.client.request.assert_called_once_with(
            'POST', 'testresource', json={"name": "Widget", "code": "W1", "status": "active"}, params=None, files=None
        )

    def test_update(self):
        data = {"name": "Widget"}
        self.resource.update("r123", data)
        self.client.request.assert_called_once_with(
            'PUT', 'testresource/r123', json={"name": "Widget"}, params=None, files=None
        )

    def test_delete(self):
        self.resource.delete("r123")
        self.client.request.assert_called_once_with('DELETE', 'testresource/r123', params=None)


class TestCustomerValidator(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.validator = CustomerValidator(self.client)

    def test_check_proper_casing(self):
        self.assertEqual(self.validator.check_proper_casing("John Doe"), [])
        self.assertEqual(self.validator.check_proper_casing("john doe"), ["john", "doe"])
        # acronyms and allowed lower case
        self.assertEqual(self.validator.check_proper_casing("TNEB Office and Shop"), [])

    def test_check_punctuation_anomalies(self):
        self.assertEqual(self.validator.check_punctuation_anomalies("Hello World"), [])
        self.assertIn("Double space", self.validator.check_punctuation_anomalies("Hello  World"))
        self.assertIn("Duplicate commas", self.validator.check_punctuation_anomalies("Hello,, World"))
        self.assertIn("Space before punctuation", self.validator.check_punctuation_anomalies("Hello ."))

    def test_check_phone_isd(self):
        self.assertIsNone(self.validator.check_phone_isd("+919876543210"))
        self.assertIsNotNone(self.validator.check_phone_isd("9876543210")) # missing +

    def test_check_geographic_name(self):
        contact = {
            "contact_name": "Trichy Fan Center",
            "billing_address": {"city": "Tiruchirappalli"},
            "custom_fields": [
                {"label": "District", "value": "Trichy"}
            ]
        }
        self.assertIsNone(self.validator.check_geographic_name(contact))

        contact_fail = {
            "contact_name": "Madurai Fan Center",
            "billing_address": {"city": "Tiruchirappalli"}
        }
        self.assertIsNotNone(self.validator.check_geographic_name(contact_fail))

    def test_check_custom_fields(self):
        contact = {
            "custom_fields": [
                {"label": "Branch", "value": "B1"},
                {"label": "District", "value": "D1"},
                {"label": "Jurisdiction", "value": "J1"},
                {"label": "Transport", "value": "T1"}
            ]
        }
        self.assertEqual(self.validator.check_custom_fields(contact), [])
        
        contact_missing = {
            "custom_fields": [
                {"label": "Branch", "value": "B1"}
            ]
        }
        self.assertEqual(len(self.validator.check_custom_fields(contact_missing)), 3)


class TestGST(unittest.TestCase):
    def test_parse_doc_number(self):
        self.assertEqual(parse_doc_number("INV-00005"), ("INV-", 5, 5))
        self.assertEqual(parse_doc_number("SO123"), ("SO", 123, 3))
        self.assertEqual(parse_doc_number(""), ("", 0, 0))

    def test_get_month_date_range(self):
        client = MagicMock()
        gst = GST(client)
        self.assertEqual(gst.get_month_date_range("2023-02"), ("2023-02-01", "2023-02-28"))
        with self.assertRaises(ValueError):
            gst.get_month_date_range("invalid-date")

    def test_get_gstr_outward_supplies(self):
        client = MagicMock()
        gst = GST(client)
        gst.get_gstr_outward_supplies(params={"accept": "xlsx"})
        client.request.assert_called_with('GET', 'reports/gstroutwardsupplies', params={"accept": "xlsx"})

    def test_get_gstr_inward_supplies(self):
        client = MagicMock()
        gst = GST(client)
        gst.get_gstr_inward_supplies(params={"accept": "xlsx"})
        client.request.assert_called_with('GET', 'reports/gstrinwardsupplies', params={"accept": "xlsx"})

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("os.makedirs")
    def test_download_gstr_outward_supplies(self, mock_makedirs, mock_open):
        client = MagicMock()
        gst = GST(client)
        gst.get_gstr_outward_supplies = MagicMock(return_value=b"outward_report_content")
        gst.download_gstr_outward_supplies("gstr1_report.xlsx", params={"accept": "xlsx"})
        gst.get_gstr_outward_supplies.assert_called_once_with(params={"accept": "xlsx"})
        mock_open.assert_called_once()
        mock_open().write.assert_called_once_with(b"outward_report_content")

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("os.makedirs")
    def test_download_gstr_inward_supplies(self, mock_makedirs, mock_open):
        client = MagicMock()
        gst = GST(client)
        gst.get_gstr_inward_supplies = MagicMock(return_value=b"inward_report_content")
        gst.download_gstr_inward_supplies("gstr2_report.xlsx", params={"accept": "xlsx"})
        gst.get_gstr_inward_supplies.assert_called_once_with(params={"accept": "xlsx"})
        mock_open.assert_called_once()
        mock_open().write.assert_called_once_with(b"inward_report_content")


class TestSalesOrders(unittest.TestCase):
    @patch("requests.request")
    def test_create_from_yaml(self, mock_request):
        from zoho.books.resources.sales import SalesOrders
        client = ZohoBooksAPI(access_token="tok", organization_id="org123", domain="com")
        sales_orders = SalesOrders(client)

        yaml_content = """
inv:
  no: "999"
  date: "2023-04-12"
items:
  - sku: "FAN-POLYCAB"
    qty: "5"
    rate: "1200"
"""
        # Mock requests
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_request.return_value = mock_response

        # Mock the items lookup to return matched item ID
        client.items.list_all = MagicMock(return_value=[
            {"sku": "FAN-POLYCAB", "item_id": "poly123", "rate": 1200}
        ])

        res = sales_orders.create_from_yaml(yaml_content, customer_id="cust123")
        self.assertEqual(res, {"status": "ok"})


class TestProjectsAndTimeEntries(unittest.TestCase):
    def test_projects_clone(self):
        client = MagicMock()
        projects = Projects(client)
        projects.clone("p123", {"name": "Clone"})
        client.request.assert_called_once_with('POST', 'projects/p123/clone', json={"name": "Clone"}, params=None)

    def test_time_entries_timer(self):
        client = MagicMock()
        te = TimeEntries(client)
        te.start_timer("te123")
        client.request.assert_called_with('POST', 'projects/timeentries/te123/timer/start', json=None, params=None)

        te.stop_timer()
        client.request.assert_called_with('POST', 'projects/timeentries/timer/stop', json=None, params=None)


class TestBooksCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_put_and_delete(self, mock_post, mock_request):
        mock_response_catalyst = MagicMock()
        mock_response_catalyst.status_code = 200
        mock_response_catalyst.json.return_value = {
            "status": "success",
            "tokens": {"books": "catalyst_books_token"}
        }
        mock_post.return_value = mock_response_catalyst

        mock_response_zoho = MagicMock()
        mock_response_zoho.status_code = 200
        mock_response_zoho.json.return_value = {"status": "ok"}
        mock_response_zoho.text = '{"status": "ok"}'
        mock_request.return_value = mock_response_zoho

        from zoho.auth import CatalystAuth
        auth = CatalystAuth(
            direct_token="direct_token",
            catalyst_token_url="http://localhost:3000/server/new/tokens",
            service_key="books"
        )
        client = ZohoBooksAPI(
            access_token=auth,
            organization_id="org123"
        )

        client.request("GET", "invoices")
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        mock_request.reset_mock()
        client.request("POST", "invoices", json={})
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        mock_request.reset_mock()
        client.request("PUT", "invoices/inv123", json={})
        mock_post.assert_called_once_with(
            "http://localhost:3000/server/new/tokens",
            headers={"Content-Type": "application/json"},
            json={},
            timeout=10
        )
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_books_token")

        mock_request.reset_mock()
        mock_post.reset_mock()
        client.request("DELETE", "invoices/inv123")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_books_token")


class TestContactsAndVendorsStatements(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.organization_id = "org123"
        from zoho.books.resources.contacts import Contacts, Vendors
        self.contacts = Contacts(self.client)
        self.vendors = Vendors(self.client)

    def test_get_statement_contacts(self):
        self.contacts.get_statement("c123", params={"accept": "xls"})
        self.client.request.assert_called_with('GET', 'contacts/c123/statements', params={"accept": "xls"}, json=None)

    def test_get_statement_vendors(self):
        self.vendors.get_statement("v123", params={"accept": "xls"})
        self.client.request.assert_called_with('GET', 'vendors/v123/statements', params={"accept": "xls"}, json=None)

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("os.makedirs")
    def test_download_statement_contacts(self, mock_makedirs, mock_open):
        self.contacts.get_statement = MagicMock(return_value=b"xls_content")
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "statement.xls")
            self.contacts.download_statement("c123", save_path)
            self.contacts.get_statement.assert_called_once_with("c123", params={"accept": "xls"})
            mock_open.assert_called_once_with(save_path, "wb")
            mock_open().write.assert_called_once_with(b"xls_content")

if __name__ == "__main__":
    unittest.main()
