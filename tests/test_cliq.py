import unittest
from unittest.mock import patch, MagicMock
from zoho.cliq import ZohoCliqAPI

class TestZohoCliqAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.bot_name = "testbot"
        self.domain = "com"
        self.client = ZohoCliqAPI(access_token=self.access_token, bot_name=self.bot_name, domain=self.domain)

    def test_init(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.bot_name, self.bot_name)
        self.assertEqual(self.client.domain, self.domain)
        self.assertEqual(self.client.base_url, "https://cliq.zoho.com/api/v2")

    def test_init_defaults(self):
        client = ZohoCliqAPI(access_token=self.access_token)
        self.assertEqual(client.bot_name, "messengerbot")
        self.assertEqual(client.domain, "in")
        self.assertEqual(client.base_url, "https://cliq.zoho.in/api/v2")

    @patch("zoho.cliq.client.logger")
    def test_send_notification_no_token(self, mock_logger):
        client = ZohoCliqAPI(access_token=None)
        res = client.send_notification("Hello")
        self.assertIsNone(res)
        mock_logger.warning.assert_called_with("Cliq Access Token not provided. Skipping notification.")

    @patch("requests.post")
    def test_send_notification_to_bot(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        res = self.client.send_notification("Hello Bot")
        
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://cliq.zoho.com/api/v2/bots/testbot/message",
            headers={
                "Authorization": "Zoho-oauthtoken fake_access_token",
                "Content-Type": "application/json"
            },
            json={"text": "Hello Bot"},
            timeout=10
        )

    @patch("requests.post")
    def test_send_notification_to_channel(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        res = self.client.send_notification("Hello Channel", channel="general")
        
        self.assertEqual(res, {"status": "success"})
        mock_post.assert_called_once_with(
            "https://cliq.zoho.com/api/v2/channels/general/message",
            headers={
                "Authorization": "Zoho-oauthtoken fake_access_token",
                "Content-Type": "application/json"
            },
            json={"text": "Hello Channel"},
            timeout=10
        )

    @patch("requests.post")
    def test_send_notification_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        res = self.client.send_notification("Hello Fail")
        self.assertIsNone(res)

if __name__ == "__main__":
    unittest.main()
