import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile
from pathlib import Path
from zoho.wd import ZohoWorkdriveAPI
from zoho.wd.exceptions import ZohoWorkdriveError

class TestZohoWorkdriveAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.client = ZohoWorkdriveAPI(access_token=self.access_token, domain="in", team_id="team123")

    def test_init(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.domain, "in")
        self.assertEqual(self.client.base_url, "https://www.zohoapis.in/workdrive/api/v1")
        self.assertEqual(self.client.get_team_id(), "team123")

    @patch("requests.request")
    def test_get_team_id_fallback(self, mock_request):
        client = ZohoWorkdriveAPI(access_token="tok", domain="in", team_id=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": {"attributes": {"preferred_team_id": "team456"}}}'
        mock_response.json.return_value = {"data": {"attributes": {"preferred_team_id": "team456"}}}
        mock_request.return_value = mock_response

        team_id = client.get_team_id()
        self.assertEqual(team_id, "team456")
        self.assertEqual(client._team_id, "team456")

    @patch("requests.request")
    def test_get_team_id_failure(self, mock_request):
        client = ZohoWorkdriveAPI(access_token="tok", domain="in", team_id=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": {"attributes": {}}}'
        mock_response.json.return_value = {"data": {"attributes": {}}}
        mock_request.return_value = mock_response

        with self.assertRaises(ZohoWorkdriveError):
            client.get_team_id()

    @patch("requests.request")
    def test_request_token_refresh(self, mock_request):
        token_callback = MagicMock(return_value="new_token")
        client = ZohoWorkdriveAPI(access_token="old_token", domain="in", token_refresh_callback=token_callback)
        
        # 401 response first, then 200 response
        mock_response1 = MagicMock()
        mock_response1.status_code = 401
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.content = b'{"status": "ok"}'
        mock_response2.json.return_value = {"status": "ok"}
        
        mock_request.side_effect = [mock_response1, mock_response2]

        res = client.request("GET", "test")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(client.access_token, "new_token")
        token_callback.assert_called_once()
        self.assertEqual(mock_request.call_count, 2)


class TestWorkdriveFiles(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.domain = "in"
        from zoho.wd.resources.files import Files
        self.files = Files(self.client)

    def test_list_files(self):
        self.files.list_files("folder1", params={"filter": "all"})
        self.client.request.assert_called_once_with('GET', 'files/folder1/files', params={"filter": "all"})

    def test_list_all_files(self):
        # 2 pages: page 1 returns 100 items, page 2 returns 5 items
        page1 = {"data": [{"id": f"f{i}"} for i in range(100)]}
        page2 = {"data": [{"id": "f100"}, {"id": "f101"}]}
        self.client.request.side_effect = [page1, page2]

        res = self.files.list_all_files("folder1")
        self.assertEqual(len(res), 102)
        self.assertEqual(self.client.request.call_count, 2)

    def test_safe_download_name(self):
        self.assertEqual(self.files._safe_download_name("hello/world.txt", "fallback"), "hello_world.txt")
        self.assertEqual(self.files._safe_download_name("", "fallback"), "fallback")
        self.assertEqual(self.files._safe_download_name("   ", "fallback"), "fallback")
        self.assertEqual(self.files._safe_download_name("..", "fallback"), "fallback")

    def test_is_folder_item(self):
        self.assertTrue(self.files._is_folder_item({"attributes": {"is_folder": True}}))
        self.assertTrue(self.files._is_folder_item({"type": "folders"}))
        self.assertTrue(self.files._is_folder_item({"attributes": {"type": "folder"}}))
        self.assertFalse(self.files._is_folder_item({"attributes": {"is_folder": False}}))

    def test_item_name(self):
        self.assertEqual(self.files._item_name({"attributes": {"name": "test.txt"}}), "test.txt")
        self.assertEqual(self.files._item_name({"name": "test.txt"}), "test.txt")
        self.assertEqual(self.files._item_name({"id": "id123"}), "id123")

    def test_next_available_download_path(self):
        reserved = set()
        p = Path("/tmp/test.txt")
        res1 = self.files._next_available_download_path(p, reserved)
        self.assertEqual(res1, p)
        res2 = self.files._next_available_download_path(p, reserved)
        self.assertEqual(res2, Path("/tmp/test (1).txt"))
        res3 = self.files._next_available_download_path(p, reserved)
        self.assertEqual(res3, Path("/tmp/test (2).txt"))

    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_download(self, mock_file):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        self.client.request.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "out.txt")
            self.files.download("file123", save_path)
            self.client.request.assert_called_once_with(
                'GET', '', stream=True, override_url="https://download.zoho.in/v1/workdrive/download/file123"
            )
            mock_file.assert_called_once_with(os.path.abspath(save_path), 'wb')

    def test_create_folder(self):
        self.files.create_folder("new_dir", "parent_id")
        self.client.request.assert_called_once_with(
            'POST', 'files', json={
                "data": {"attributes": {"name": "new_dir", "parent_id": "parent_id"}, "type": "files"}
            }
        )

    def test_delete(self):
        self.files.delete("file123")
        self.client.request.assert_called_once_with('DELETE', 'files/file123')

    def test_move(self):
        self.files.move("file123", "folder123")
        self.client.request.assert_called_once_with(
            'PATCH', 'files/file123', json={
                "data": {"attributes": {"parent_id": "folder123"}, "type": "files"}
            },
            params=None
        )

    def test_search(self):
        self.client.get_team_id.return_value = "team123"
        self.client.request.return_value = {"data": [{"id": "res1"}]}
        res = self.files.search("my_file", parent_id="p123", resource_type="file")
        self.assertEqual(res, [{"id": "res1"}])
        self.client.request.assert_called_once_with(
            'GET', 'organization/team123/records', params={
                "search[all]": "my_file",
                "filter[parentId]": "p123",
                "filter[type]": "file"
            }
        )

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_upload(self, mock_file, mock_exists):
        self.files.upload("folder123", "dummy.png")
        self.client.request.assert_called_once()
        args, kwargs = self.client.request.call_args
        self.assertEqual(args[0], 'POST')
        self.assertEqual(args[1], 'upload')
        self.assertEqual(kwargs['params'], {"parent_id": "folder123"})
        self.assertIn('content', kwargs['files'])

    def test_get_base_name(self):
        self.assertEqual(self.files.get_base_name("Doc 1"), "Doc 1")
        self.assertEqual(self.files.get_base_name("Doc 1 20-04-2023 10:11:12:000"), "Doc 1")
        self.assertEqual(self.files.get_base_name("Doc 1 (2)"), "Doc 1")

    def test_merge_folders(self):
        # s_item: "sub1" (folder), "file1" (file)
        # target_items: empty
        self.files.list_all_files = MagicMock(side_effect=[
            [
                {"id": "sub1", "attributes": {"name": "sub1", "is_folder": True}},
                {"id": "file1", "attributes": {"name": "file1", "is_folder": False}}
            ],
            []
        ])
        self.files.move = MagicMock()
        
        self.files.merge_folders("source_id", "target_id", "folder_name")
        self.assertEqual(self.files.move.call_count, 2)
        self.files.move.assert_any_call("sub1", "target_id")
        self.files.move.assert_any_call("file1", "target_id")

    def test_cleanup_duplicates(self):
        # Folder contains "FolderA" and duplicate "FolderA (1)"
        self.files.list_all_files = MagicMock(side_effect=[
            [
                {"id": "f_orig", "attributes": {"name": "FolderA", "is_folder": True}},
                {"id": "f_dup", "attributes": {"name": "FolderA (1)", "is_folder": True}}
            ],
            []
        ])
        self.files.merge_folders = MagicMock()
        self.files.delete = MagicMock()

        self.files.cleanup_duplicates("parent_id", recursive=True)
        self.files.merge_folders.assert_called_once_with("f_dup", "f_orig", "FolderA (1)")
        self.files.delete.assert_called_once_with("f_dup")

class TestWorkdriveCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_mutations(self, mock_post, mock_request):
        mock_response_catalyst = MagicMock()
        mock_response_catalyst.status_code = 200
        mock_response_catalyst.json.return_value = {
            "status": "success",
            "tokens": {"workdrive": "catalyst_wd_token"}
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
            service_key="workdrive"
        )
        client = ZohoWorkdriveAPI(
            access_token=auth,
            domain="in",
            team_id="team123"
        )

        # GET request should not use Catalyst
        client.request("GET", "files/some_id")
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        # POST request should not use Catalyst
        mock_request.reset_mock()
        client.request("POST", "files", json={})
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        # PUT request should use Catalyst
        mock_request.reset_mock()
        client.request("PUT", "files/some_id", json={})
        mock_post.assert_called_once_with(
            "http://localhost:3000/server/new/tokens",
            headers={"Content-Type": "application/json"},
            json={},
            timeout=10
        )
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_wd_token")

        # PATCH request should use Catalyst
        mock_request.reset_mock()
        mock_post.reset_mock()
        client.request("PATCH", "files/some_id", json={})
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_wd_token")

        # DELETE request should use Catalyst
        mock_request.reset_mock()
        mock_post.reset_mock()
        client.request("DELETE", "files/some_id")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_wd_token")


if __name__ == "__main__":
    unittest.main()

