import unittest
from unittest.mock import patch, MagicMock
from zoho.creator import ZohoCreatorAPI, ZohoCreatorError
from zoho.auth import CatalystAuth

class TestZohoCreatorAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_creator_token"
        self.owner = "john_owner"
        self.client = ZohoCreatorAPI(
            access_token=self.access_token,
            account_owner_name=self.owner,
            domain="com"
        )

    def test_init(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.account_owner_name, self.owner)
        self.assertEqual(self.client.domain, "com")
        self.assertEqual(self.client.environment, "production")
        self.assertEqual(self.client.base_url, "https://www.zohoapis.com/creator/v2.1")

    @patch("requests.request")
    def test_request_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_request.return_value = mock_response

        res = self.client.request("GET", "meta/john_owner/applications")
        self.assertEqual(res, {"status": "ok"})
        mock_request.assert_called_once_with(
            method="GET",
            url="https://www.zohoapis.com/creator/v2.1/meta/john_owner/applications",
            headers={
                "Authorization": "Zoho-oauthtoken fake_creator_token",
                "environment": "production"
            },
            params=None,
            json=None,
            timeout=30
        )

    @patch("requests.request")
    def test_request_401_refresh_success(self, mock_request):
        token_callback = MagicMock(return_value="refreshed_token")
        client = ZohoCreatorAPI(
            access_token="old_token",
            account_owner_name="owner123",
            token_refresh_callback=token_callback
        )

        mock_response_401 = MagicMock()
        mock_response_401.status_code = 401
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"status": "success"}

        mock_request.side_effect = [mock_response_401, mock_response_200]

        res = client.request("GET", "test_endpoint")
        self.assertEqual(res, {"status": "success"})
        self.assertEqual(client.access_token, "refreshed_token")
        token_callback.assert_called_once()
        self.assertEqual(mock_request.call_count, 2)

    @patch("requests.request")
    def test_request_failure(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"code": 3001, "message": "Invalid Parameter"}
        mock_request.return_value = mock_response

        with self.assertRaises(ZohoCreatorError) as ctx:
            self.client.request("GET", "bad")
        self.assertIn("Invalid Parameter", str(ctx.exception))


class TestCreatorNativeAPIs(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.account_owner_name = "owner123"
        self.client.domain = "com"
        self.client.environment = "production"

    def test_list_applications(self):
        ZohoCreatorAPI.list_applications(self.client)
        self.client.request.assert_called_once_with("GET", "meta/owner123/applications")

    def test_list_forms(self):
        ZohoCreatorAPI.list_forms(self.client, "app_link")
        self.client.request.assert_called_once_with("GET", "meta/owner123/app_link/forms")

    def test_list_reports(self):
        ZohoCreatorAPI.list_reports(self.client, "app_link")
        self.client.request.assert_called_once_with("GET", "meta/owner123/app_link/reports")

    def test_get_fields(self):
        ZohoCreatorAPI.get_fields(self.client, "app_link", "form_link")
        self.client.request.assert_called_once_with("GET", "meta/owner123/app_link/form/form_link/fields")

    def test_get_records(self):
        params = {"criteria": "Name == 'John'"}
        ZohoCreatorAPI.get_records(self.client, "app_link", "report_link", params=params)
        self.client.request.assert_called_once_with("GET", "data/owner123/app_link/report/report_link", params=params)

    def test_add_records(self):
        payload = {"data": [{"Name": "John"}]}
        ZohoCreatorAPI.add_records(self.client, "app_link", "form_link", payload)
        self.client.request.assert_called_once_with("POST", "data/owner123/app_link/form/form_link", json=payload, params=None)

    def test_update_records_with_id(self):
        payload = {"data": {"Name": "John"}}
        ZohoCreatorAPI.update_records(self.client, "app_link", "report_link", payload, record_id="rec123")
        self.client.request.assert_called_once_with("PATCH", "data/owner123/app_link/report/report_link/rec123", json=payload, params=None)

    def test_update_records_with_criteria(self):
        payload = {"data": {"Name": "John"}}
        ZohoCreatorAPI.update_records(self.client, "app_link", "report_link", payload, params={"criteria": "Age > 30"})
        self.client.request.assert_called_once_with("PATCH", "data/owner123/app_link/report/report_link", json=payload, params={"criteria": "Age > 30"})

    def test_delete_records_with_id(self):
        ZohoCreatorAPI.delete_records(self.client, "app_link", "report_link", record_id="rec123")
        self.client.request.assert_called_once_with("DELETE", "data/owner123/app_link/report/report_link/rec123", params=None)

    def test_delete_records_with_criteria(self):
        ZohoCreatorAPI.delete_records(self.client, "app_link", "report_link", params={"criteria": "Age > 30"})
        self.client.request.assert_called_once_with("DELETE", "data/owner123/app_link/report/report_link", params={"criteria": "Age > 30"})


class TestCreatorCustomSDKFunctions(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.account_owner_name = "owner123"

    def test_get_all_records_pagination(self):
        # First call returns record_cursor in page_context
        page_1 = {
            "data": [{"id": 1}, {"id": 2}],
            "page_context": {"record_cursor": "cursor_token_abc"}
        }
        # Second call returns no cursor
        page_2 = {
            "data": [{"id": 3}]
        }
        self.client.get_records.side_effect = [page_1, page_2]

        records = ZohoCreatorAPI.get_all_records(self.client, "app_link", "report_link")
        self.assertEqual(records, [{"id": 1}, {"id": 2}, {"id": 3}])
        
        # Check call parameters
        self.client.get_records.assert_any_call("app_link", "report_link", params={"max_records": 1000})
        self.client.get_records.assert_any_call("app_link", "report_link", params={"record_cursor": "cursor_token_abc"})

    def test_add_records_bulk(self):
        records = [{"Name": f"User {i}"} for i in range(500)]
        self.client.add_records.return_value = {"code": 3000, "message": "success"}

        responses = ZohoCreatorAPI.add_records_bulk(self.client, "app_link", "form_link", records, skip_workflow=["on_add"])
        
        # 500 records batched in 200 should call add_records 3 times (200, 200, 100)
        self.assertEqual(len(responses), 3)
        self.assertEqual(self.client.add_records.call_count, 3)
        
        # Check chunk sizes
        args1 = self.client.add_records.call_args_list[0][0]
        self.assertEqual(len(args1[2]["data"]), 200)
        self.assertEqual(args1[2]["skip_workflow"], ["on_add"])

        args3 = self.client.add_records.call_args_list[2][0]
        self.assertEqual(len(args3[2]["data"]), 100)


class TestCreatorCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_flow(self, mock_post, mock_request):
        # Mock Catalyst server response
        mock_response_catalyst = MagicMock()
        mock_response_catalyst.status_code = 200
        mock_response_catalyst.json.return_value = {
            "status": "success",
            "tokens": {"creator": "catalyst_creator_token"}
        }
        mock_post.return_value = mock_response_catalyst

        # Mock Zoho Creator API response
        mock_response_zoho = MagicMock()
        mock_response_zoho.status_code = 200
        mock_response_zoho.json.return_value = {"status": "ok"}
        mock_request.return_value = mock_response_zoho

        # Instantiate auth
        auth = CatalystAuth(
            direct_token="direct_token",
            catalyst_token_url="http://localhost:3000/creator/tokens",
            service_key="creator"
        )
        client = ZohoCreatorAPI(
            access_token=auth,
            account_owner_name="owner123"
        )

        # 1. Non-mutating request (GET) should use direct token
        client.get_records("app_link", "report_link")
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        # 2. Mutating request (POST / add_records) should use Catalyst token
        mock_request.reset_mock()
        client.add_records("app_link", "form_link", {"data": [{"Name": "A"}]})
        mock_post.assert_called_once_with(
            "http://localhost:3000/creator/tokens",
            headers={"Content-Type": "application/json"},
            json={},
            timeout=10
        )
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_creator_token")

        # 3. Mutating request (PATCH / update_records) should use Catalyst token
        mock_request.reset_mock()
        mock_post.reset_mock()
        client.update_records("app_link", "report_link", {"data": {"Name": "B"}}, record_id="rec123")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_creator_token")

        # 4. Mutating request (DELETE / delete_records) should use Catalyst token
        mock_request.reset_mock()
        mock_post.reset_mock()
        client.delete_records("app_link", "report_link", record_id="rec123")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_creator_token")


if __name__ == "__main__":
    unittest.main()
