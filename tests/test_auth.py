import unittest
from unittest.mock import patch, MagicMock
import time
from zoho.auth import ZohoOAuth2Manager

class TestZohoOAuth2Manager(unittest.TestCase):
    def setUp(self):
        self.client_id = "test_client_id"
        self.client_secret = "test_client_secret"
        self.refresh_token = "test_refresh_token"
        self.domain = "com"
        self.manager = ZohoOAuth2Manager(
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            domain=self.domain
        )

    def test_init(self):
        self.assertEqual(self.manager.client_id, self.client_id)
        self.assertEqual(self.manager.client_secret, self.client_secret)
        self.assertEqual(self.manager.refresh_token, self.refresh_token)
        self.assertEqual(self.manager.domain, self.domain)
        self.assertIsNone(self.manager._access_token)
        self.assertEqual(self.manager._expires_at, 0.0)

    def test_get_token_url(self):
        self.assertEqual(self.manager.get_token_url(), "https://accounts.zoho.com/oauth/v2/token")
        
        manager_in = ZohoOAuth2Manager("cid", "sec", "ref", domain="in")
        self.assertEqual(manager_in.get_token_url(), "https://accounts.zoho.in/oauth/v2/token")

    @patch("requests.post")
    def test_refresh_access_token_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token_123",
            "expires_in": 3600
        }
        mock_post.return_value = mock_response

        token = self.manager.refresh_access_token()
        self.assertEqual(token, "new_access_token_123")
        self.assertEqual(self.manager._access_token, "new_access_token_123")
        self.assertTrue(self.manager._expires_at > time.time())
        
        mock_post.assert_called_once_with(
            "https://accounts.zoho.com/oauth/v2/token",
            data={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token"
            },
            timeout=10
        )

    @patch("requests.post")
    def test_refresh_access_token_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": "invalid_code"
        }
        mock_post.return_value = mock_response

        with self.assertRaises(ValueError):
            self.manager.refresh_access_token()

    @patch("requests.post")
    def test_get_access_token_expired(self, mock_post):
        # Setup expired token
        self.manager._access_token = "old_token"
        self.manager._expires_at = time.time() - 10 # expired 10 seconds ago

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "refreshed_token",
            "expires_in": 3600
        }
        mock_post.return_value = mock_response

        token = self.manager.get_access_token()
        self.assertEqual(token, "refreshed_token")
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_get_access_token_cached(self, mock_post):
        # Setup valid token
        self.manager._access_token = "valid_cached_token"
        self.manager._expires_at = time.time() + 1000 # expires in 1000 seconds

        token = self.manager.get_access_token()
        self.assertEqual(token, "valid_cached_token")
        mock_post.assert_not_called()

    def test_keyring_success(self):
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "secret_refresh_token"
        
        import sys
        new_modules = sys.modules.copy()
        new_modules["keyring"] = mock_keyring
        
        with patch.dict("sys.modules", new_modules):
            manager = ZohoOAuth2Manager(
                client_id="cid",
                client_secret="sec",
                keyring_service="zoho_service",
                keyring_username="zoho_user"
            )
            self.assertEqual(manager.refresh_token, "secret_refresh_token")
            mock_keyring.get_password.assert_called_once_with("zoho_service", "zoho_user")

    def test_keyring_missing_token(self):
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        
        import sys
        new_modules = sys.modules.copy()
        new_modules["keyring"] = mock_keyring
        
        with patch.dict("sys.modules", new_modules):
            manager = ZohoOAuth2Manager(
                client_id="cid",
                client_secret="sec",
                keyring_service="zoho_service",
                keyring_username="zoho_user"
            )
            with self.assertRaises(ValueError):
                _ = manager.refresh_token

    def test_keyring_import_error(self):
        import builtins
        real_import = builtins.__import__
        
        def mock_import(name, *args, **kwargs):
            if name == 'keyring':
                raise ImportError("No module named 'keyring'")
            return real_import(name, *args, **kwargs)
            
        with patch("builtins.__import__", side_effect=mock_import):
            manager = ZohoOAuth2Manager(
                client_id="cid",
                client_secret="sec",
                keyring_service="zoho_service",
                keyring_username="zoho_user"
            )
            with self.assertRaises(ImportError):
                _ = manager.refresh_token

    def test_keyring_missing_params(self):
        manager = ZohoOAuth2Manager(
            client_id="cid",
            client_secret="sec"
        )
        with self.assertRaises(ValueError):
            _ = manager.refresh_token

if __name__ == "__main__":
    unittest.main()
