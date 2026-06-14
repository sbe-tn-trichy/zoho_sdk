import unittest
from unittest.mock import patch, MagicMock
import json
from zoho.sheet import ZohoSheetAPI

class TestZohoSheetAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.client = ZohoSheetAPI(access_token=self.access_token, domain="com")

    def test_init(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.domain, "com")
        self.assertEqual(self.client.base_url, "https://sheet.zoho.com/api/v2")

    def test_get_headers(self):
        headers = self.client._get_headers()
        self.assertEqual(headers, {"Authorization": "Zoho-oauthtoken fake_access_token"})

    @patch("requests.get")
    def test_list_workbooks_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"workbooks": [{"id": "wb1", "name": "Workbook 1"}]}
        mock_get.return_value = mock_response

        res = self.client.list_workbooks()
        self.assertEqual(res, [{"id": "wb1", "name": "Workbook 1"}])
        mock_get.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/workbooks",
            headers=self.client._get_headers(),
            params={"method": "workbook.list"}
        )

    @patch("requests.post")
    def test_list_sheets_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"worksheet_names": [{"name": "Sheet1"}]}
        mock_post.return_value = mock_response

        res = self.client.list_sheets("wb1")
        self.assertEqual(res, [{"name": "Sheet1"}])
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.list"}
        )

    @patch("requests.get")
    def test_get_rows_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"records": [{"col1": "val1"}]}
        mock_get.return_value = mock_response

        res = self.client.get_rows("wb1", "Sheet1", limit=10)
        self.assertEqual(res, [{"col1": "val1"}])
        mock_get.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={
                "method": "worksheet.records.fetch",
                "worksheet_name": "Sheet1",
                "limit": 10
            }
        )

    @patch("requests.get")
    def test_get_rows_no_records_graceful(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 400 # or whatever code returned for error 2884
        mock_response.json.return_value = {"error_code": 2884, "message": "No records found"}
        mock_get.return_value = mock_response

        res = self.client.get_rows("wb1", "Sheet1")
        self.assertEqual(res, [])

    @patch("requests.post")
    def test_set_content(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        data = [["A1", "B1"]]
        res = self.client.set_content("wb1", "Sheet1", "A1:B1", data)
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.content.set"},
            data={
                "worksheet_name": "Sheet1",
                "range": "A1:B1",
                "json_data": json.dumps(data)
            }
        )

    @patch("requests.post")
    def test_set_cell(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        res = self.client.set_cell("wb1", "Sheet1", 1, 1, "Hello")
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "cell.content.set"},
            data={
                "worksheet_name": "Sheet1",
                "row": 1,
                "column": 1,
                "content": "Hello"
            }
        )

    @patch("requests.post")
    def test_add_sheet(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        res = self.client.add_sheet("wb1", "NewSheet")
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.add"},
            data={
                "worksheet_name": "NewSheet"
            }
        )

    @patch("requests.post")
    def test_add_rows(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        rows_data = [{"Name": "John", "Age": 30}]
        res = self.client.add_rows("wb1", "Sheet1", rows_data, header_row=2)
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.add"},
            data={
                "worksheet_name": "Sheet1",
                "json_data": json.dumps(rows_data),
                "header_row": 2
            }
        )

    @patch("requests.post")
    def test_update_rows(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        rows_data = {"Age": 31}
        res = self.client.update_rows("wb1", "Sheet1", "Name='John'", rows_data)
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.update"},
            data={
                "worksheet_name": "Sheet1",
                "criteria": "Name='John'",
                "json_data": json.dumps(rows_data)
            }
        )

    @patch("requests.post")
    def test_truncate_sheet(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        res = self.client.truncate_sheet("wb1", "Sheet1")
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.delete"},
            data={
                "worksheet_name": "Sheet1",
                "criteria": "(row_index != 0)"
            }
        )

class TestSheetCatalystAuth(unittest.TestCase):
    @patch("requests.post")
    def test_catalyst_auth_flow(self, mock_post):
        # Setup mock responses based on request URL
        def mock_post_side_effect(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "localhost" in url or "tokens" in url:
                resp.json.return_value = {
                    "status": "success",
                    "tokens": {"sheet": "catalyst_sheet_token"}
                }
            else:
                resp.json.return_value = {"status": "success"}
            return resp

        mock_post.side_effect = mock_post_side_effect

        from zoho.auth import CatalystAuth
        auth = CatalystAuth(
            direct_token="direct_token",
            catalyst_token_url="http://localhost:3000/server/new/tokens",
            service_key="sheet"
        )
        client = ZohoSheetAPI(
            access_token=auth,
            domain="in"
        )

        # 1. Non-mutating header check
        headers_non_mut = client._get_headers()
        self.assertEqual(headers_non_mut["Authorization"], "Zoho-oauthtoken direct_token")

        # 2. Call a mutating method and verify the Authorization header passed
        # set_cell is a mutating method
        mock_post.reset_mock()
        res = client.set_cell("wb123", "Sheet1", 1, 1, "hello")
        self.assertEqual(res, {"status": "success"})
        
        # There should be 2 post calls: 1 to Catalyst token endpoint, 1 to Zoho Sheet API
        self.assertEqual(mock_post.call_count, 2)
        
        # Check first call is Catalyst URL
        first_call_args, first_call_kwargs = mock_post.call_args_list[0]
        self.assertEqual(first_call_args[0], "http://localhost:3000/server/new/tokens")

        # Check second call is Zoho Sheet API with catalyst token in headers
        second_call_args, second_call_kwargs = mock_post.call_args_list[1]
        self.assertEqual(second_call_args[0], "https://sheet.zoho.in/api/v2/wb123")
        self.assertEqual(second_call_kwargs["headers"]["Authorization"], "Zoho-oauthtoken catalyst_sheet_token")



if __name__ == "__main__":
    unittest.main()

