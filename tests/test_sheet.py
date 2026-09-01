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

    @patch("requests.request")
    def test_list_workbooks_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"workbooks": [{"id": "wb1", "name": "Workbook 1"}]}
        mock_request.return_value = mock_response

        res = self.client.list_workbooks()
        self.assertEqual(res, [{"id": "wb1", "name": "Workbook 1"}])
        mock_request.assert_called_once_with(
            method="GET",
            url="https://sheet.zoho.com/api/v2/workbooks",
            headers=self.client._get_headers(),
            params={"method": "workbook.list"},
            timeout=30,
        )

    @patch("requests.request")
    def test_list_sheets_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"worksheet_names": [{"name": "Sheet1"}]}
        mock_request.return_value = mock_response

        res = self.client.list_sheets("wb1")
        self.assertEqual(res, ["Sheet1"])
        self.assertIsInstance(res[0], str)
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.list"},
            timeout=30,
        )

    @patch("requests.request")
    def test_get_rows_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"records": [{"col1": "val1"}]}
        mock_request.return_value = mock_response

        res = self.client.get_rows("wb1", "Sheet1", limit=10)
        self.assertEqual(res, [{"col1": "val1"}])
        mock_request.assert_called_once_with(
            method="GET",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={
                "method": "worksheet.records.fetch",
                "worksheet_name": "Sheet1",
                "limit": 10
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_get_rows_no_records_graceful(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 400 # or whatever code returned for error 2884
        mock_response.json.return_value = {"error_code": 2884, "message": "No records found"}
        mock_request.return_value = mock_response

        res = self.client.get_rows("wb1", "Sheet1")
        self.assertEqual(res, [])

    @patch("requests.request")
    def test_set_content(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        data = [["A1", "B1"]]
        res = self.client.set_content("wb1", "Sheet1", "A1:B1", data)
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.content.set"},
            data={
                "worksheet_name": "Sheet1",
                "range": "A1:B1",
                "json_data": json.dumps(data)
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_set_cell(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        res = self.client.set_cell("wb1", "Sheet1", 1, 1, "Hello")
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "cell.content.set"},
            data={
                "worksheet_name": "Sheet1",
                "row": 1,
                "column": 1,
                "content": "Hello"
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_add_sheet(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        res = self.client.add_sheet("wb1", "NewSheet")
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.add"},
            data={
                "worksheet_name": "NewSheet"
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_add_rows(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        rows_data = [{"Name": "John", "Age": 30}]
        res = self.client.add_rows("wb1", "Sheet1", rows_data, header_row=2)
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.add"},
            data={
                "worksheet_name": "Sheet1",
                "json_data": json.dumps(rows_data),
                "header_row": 2
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_update_rows(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        rows_data = {"Age": 31}
        res = self.client.update_rows("wb1", "Sheet1", "Name='John'", rows_data)
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.update"},
            data={
                "worksheet_name": "Sheet1",
                "criteria": "Name='John'",
                "json_data": json.dumps(rows_data)
            },
            timeout=30,
        )

    @patch("requests.request")
    def test_truncate_sheet(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        res = self.client.truncate_sheet("wb1", "Sheet1")
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="POST",
            url="https://sheet.zoho.com/api/v2/wb1",
            headers=self.client._get_headers(),
            params={"method": "worksheet.records.delete"},
            data={
                "worksheet_name": "Sheet1",
                "criteria": "(row_index != 0)"
            },
            timeout=30,
        )

class TestSheetCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_flow(self, mock_post, mock_request):
        # Setup mock responses based on request URL
        token_response = MagicMock(status_code=200)
        token_response.json.return_value = {
            "status": "success",
            "tokens": {"sheet": "catalyst_sheet_token"},
        }
        mock_post.return_value = token_response
        api_response = MagicMock(status_code=200)
        api_response.json.return_value = {"status": "success"}
        mock_request.return_value = api_response

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

        # 1. Semantically read-only POST stays on the direct token.
        api_response.json.return_value = {"worksheet_names": ["Sheet1"]}
        self.assertEqual(client.list_sheets("wb123"), ["Sheet1"])
        mock_post.assert_not_called()
        self.assertEqual(
            mock_request.call_args.kwargs["headers"]["Authorization"],
            "Zoho-oauthtoken direct_token",
        )

        # 2. Call a mutating method and verify the Authorization header passed
        # set_cell is a mutating method
        mock_post.reset_mock()
        mock_request.reset_mock()
        api_response.json.return_value = {"status": "success"}
        res = client.set_cell("wb123", "Sheet1", 1, 1, "hello")
        self.assertEqual(res, {"status": "success"})
        
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args.kwargs["url"], "https://sheet.zoho.in/api/v2/wb123")
        self.assertEqual(
            mock_request.call_args.kwargs["headers"]["Authorization"],
            "Zoho-oauthtoken catalyst_sheet_token",
        )



if __name__ == "__main__":
    unittest.main()
