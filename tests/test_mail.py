import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
from zoho.mail import ZohoMailAPI, ZohoMailError

class TestZohoMailAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.client = ZohoMailAPI(access_token=self.access_token, domain="com")

    def test_init(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.base_url, "https://mail.zoho.com/api")

    @patch("requests.request")
    def test_request_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "success"}'
        mock_response.json.return_value = {"status": "success"}
        mock_request.return_value = mock_response

        res = self.client.request("GET", "test_endpoint")
        self.assertEqual(res, {"status": "success"})
        mock_request.assert_called_once_with(
            method="GET",
            url="https://mail.zoho.com/api/test_endpoint",
            headers={
                "Authorization": "Zoho-oauthtoken fake_access_token",
                "Content-Type": "application/json"
            },
            params=None,
            json=None,
            files=None,
            stream=False
        )

    @patch("requests.request")
    def test_request_empty_or_204(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.text = ""
        mock_request.return_value = mock_response

        res = self.client.request("DELETE", "test_endpoint")
        self.assertEqual(res, {})

    @patch("requests.request")
    def test_request_failure(self, mock_request):
        import requests
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        # Simulate raise_for_status raising HTTPError
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Bad Request")
        mock_request.return_value = mock_response

        with self.assertRaises(ZohoMailError):
            self.client.request("GET", "test_endpoint")

    def test_account_scope(self):
        scope = self.client.account("acc123")
        self.assertEqual(scope.folders.account_id, "acc123")
        self.assertEqual(scope.messages.account_id, "acc123")


class TestFolders(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.folders = self.client.account("acc123").folders
        # For actual testing we can just instantiate it
        from zoho.mail.resources.folders import Folders
        self.folders = Folders(self.client, "acc123")

    def test_create(self):
        self.folders.create("Inbox_Sub", parent_folder_id="parent1")
        self.client.request.assert_called_with(
            'POST',
            'accounts/acc123/folders',
            json={"folderName": "Inbox_Sub", "parentFolderId": "parent1"},
            params=None,
            files=None
        )

    def test_rename(self):
        self.folders.rename("folder_id", "NewName")
        self.client.request.assert_called_with(
            'PUT',
            'accounts/acc123/folders/folder_id',
            json={"folderName": "NewName"},
            params=None,
            files=None
        )


class TestMessages(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        from zoho.mail.resources.messages import Messages
        self.messages = Messages(self.client, "acc123")

    def test_list(self):
        self.messages.list(folder_id="f123", page=2, limit=10, params={"searchKey": "test"})
        self.client.request.assert_called_once_with(
            'GET',
            'accounts/acc123/messages/view',
            params={
                "start": 11,
                "limit": 10,
                "folderId": "f123",
                "searchKey": "test"
            }
        )

    def test_get_content(self):
        self.messages.get_content("msg123")
        self.client.request.assert_called_once_with('GET', 'accounts/acc123/messages/msg123/content')

    def test_send(self):
        self.messages.send("from@zoho.com", "to@zoho.com", "Hello", "Body", askReceipt="yes")
        self.client.request.assert_called_once_with(
            'POST',
            'accounts/acc123/messages',
            json={
                "fromAddress": "from@zoho.com",
                "toAddress": "to@zoho.com",
                "subject": "Hello",
                "content": "Body",
                "action": "send",
                "askReceipt": "yes"
            },
            params=None,
            files=None
        )

    def test_save_draft(self):
        self.messages.save_draft("from@zoho.com", "to@zoho.com", "Draft", "Draft Body")
        self.client.request.assert_called_once_with(
            'POST',
            'accounts/acc123/messages',
            json={
                "fromAddress": "from@zoho.com",
                "toAddress": "to@zoho.com",
                "subject": "Draft",
                "content": "Draft Body",
                "action": "save"
            },
            params=None,
            files=None
        )

    def test_mark_as_read(self):
        self.messages.mark_as_read("msg123")
        self.client.request.assert_called_once_with(
            'PUT',
            'accounts/acc123/messages/msg123',
            json={"status": "read"},
            params=None,
            files=None
        )

    def test_mark_as_unread(self):
        self.messages.mark_as_unread("msg123")
        self.client.request.assert_called_once_with(
            'PUT',
            'accounts/acc123/messages/msg123',
            json={"status": "unread"},
            params=None,
            files=None
        )

    def test_get_attachments_info(self):
        self.messages.get_attachments_info("f123", "msg123")
        self.client.request.assert_called_once_with('GET', 'accounts/acc123/folders/f123/messages/msg123/attachmentinfo')

    def test_get_attachment_content(self):
        mock_response = MagicMock()
        mock_response.content = b"attachment_data"
        self.client.request.return_value = mock_response

        content = self.messages.get_attachment_content("f123", "msg123", "att123")
        self.assertEqual(content, b"attachment_data")
        self.client.request.assert_called_once_with(
            'GET',
            'accounts/acc123/folders/f123/messages/msg123/attachments/att123',
            stream=True
        )

    def test_list_iter(self):
        self.client.request.side_effect = [
            {"data": [{"messageId": "m1"}, {"messageId": "m2"}]},
            {"data": []}
        ]
        iterator = self.messages.list_iter(folder_id="f123", limit=2)
        results = list(iterator)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["messageId"], "m1")
        self.assertEqual(results[1]["messageId"], "m2")

    def test_message_has_attachment(self):
        self.assertTrue(self.messages.message_has_attachment({"hasAttachment": "1"}))
        self.assertTrue(self.messages.message_has_attachment({"hasAttachment": "True"}))
        self.assertTrue(self.messages.message_has_attachment({"hasAttachment": "yes"}))
        self.assertFalse(self.messages.message_has_attachment({"hasAttachment": "0"}))

    def test_extract_attachments(self):
        resp_dict = {"data": {"attachments": [{"attachmentId": "a1"}]}}
        self.assertEqual(self.messages.extract_attachments(resp_dict), [{"attachmentId": "a1"}])

        resp_list = {"data": [{"attachmentId": "a2"}]}
        self.assertEqual(self.messages.extract_attachments(resp_list), [{"attachmentId": "a2"}])

        resp_invalid = {"data": "invalid"}
        self.assertEqual(self.messages.extract_attachments(resp_invalid), [])

    def test_resolve_download_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_name = "test.txt"
            path = self.messages.resolve_download_path(tmpdir, file_name)
            self.assertEqual(path, os.path.join(tmpdir, file_name))

            # Create file to cause collision
            with open(path, "w") as f:
                f.write("exist")
            
            path2 = self.messages.resolve_download_path(tmpdir, file_name)
            self.assertEqual(path2, os.path.join(tmpdir, "test_1.txt"))

    def test_download_folder_attachments(self):
        # Mock list_iter to return one message with attachments
        self.messages.list_iter = MagicMock(return_value=[
            {"messageId": "m1", "hasAttachment": "yes"},
            {"messageId": "m2", "hasAttachment": "no"}
        ])
        
        # Mock get_attachments_info
        self.messages.get_attachments_info = MagicMock(return_value={
            "data": [{"attachmentId": "att1", "attachmentName": "file1.png"}]
        })
        
        # Mock get_attachment_content
        self.messages.get_attachment_content = MagicMock(return_value=b"fake_png_data")

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self.messages.download_folder_attachments("f123", tmpdir)
            self.assertEqual(len(paths), 1)
            self.assertTrue(os.path.exists(paths[0]))
            self.assertEqual(os.path.basename(paths[0]), "file1.png")
            with open(paths[0], "rb") as f:
                self.assertEqual(f.read(), b"fake_png_data")

class TestMailCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_mutations(self, mock_post, mock_request):
        mock_response_catalyst = MagicMock()
        mock_response_catalyst.status_code = 200
        mock_response_catalyst.json.return_value = {
            "status": "success",
            "tokens": {"zmail": "catalyst_mail_token"}
        }
        mock_post.return_value = mock_response_catalyst

        mock_response_zoho = MagicMock()
        mock_response_zoho.status_code = 200
        mock_response_zoho.json.return_value = {"status": "ok"}
        mock_response_zoho.content = b'{"status": "ok"}'
        mock_request.return_value = mock_response_zoho

        from zoho.auth import CatalystAuth
        auth = CatalystAuth(
            direct_token="direct_token",
            catalyst_token_url="http://localhost:3000/server/new/tokens",
            service_key="zmail"
        )
        client = ZohoMailAPI(
            access_token=auth,
            domain="com"
        )

        # GET request should not use Catalyst
        client.request("GET", "accounts")
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        # POST request should not use Catalyst
        mock_request.reset_mock()
        client.request("POST", "accounts", json={})
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        # PUT request should use Catalyst
        mock_request.reset_mock()
        client.request("PUT", "accounts/acc123", json={})
        mock_post.assert_called_once_with(
            "http://localhost:3000/server/new/tokens",
            headers={"Content-Type": "application/json"},
            json={},
            timeout=10
        )
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_mail_token")

        # DELETE request should use Catalyst
        mock_request.reset_mock()
        mock_post.reset_mock()
        client.request("DELETE", "accounts/acc123")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_mail_token")


if __name__ == "__main__":
    unittest.main()

