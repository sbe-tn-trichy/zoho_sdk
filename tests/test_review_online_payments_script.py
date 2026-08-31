import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.review_online_payments import _clients, main


class TestReviewOnlinePaymentsScript(unittest.TestCase):
    @patch("scripts.review_online_payments.ZohoBooksAPI")
    @patch("scripts.review_online_payments.ZohoCreatorAPI")
    @patch("scripts.review_online_payments.HttpTokenProvider")
    def test_clients_refresh_expired_service_tokens(
        self, provider_class, creator_class, books_class
    ):
        provider = MagicMock()
        provider.get_tokens.side_effect = [
            {"creator": "creator-old", "books": "books-old"},
            {"creator": "creator-new", "books": "books-new"},
            {"creator": "creator-newer", "books": "books-newer"},
        ]
        provider_class.return_value = provider

        creator, books = _clients("http://token", "owner", "org", "in")

        self.assertIs(creator, creator_class.return_value)
        self.assertIs(books, books_class.return_value)
        creator_kwargs = creator_class.call_args.kwargs
        books_kwargs = books_class.call_args.kwargs
        self.assertEqual(creator_kwargs["access_token"], "creator-old")
        self.assertEqual(books_kwargs["access_token"], "books-old")
        self.assertEqual(creator_kwargs["token_refresh_callback"](), "creator-new")
        self.assertEqual(books_kwargs["token_refresh_callback"](), "books-newer")

    @patch("scripts.review_online_payments.OnlinePaymentReviewService")
    @patch("scripts.review_online_payments._clients")
    def test_refresh_only_updates_preview_and_exits(self, clients, service_class):
        clients.return_value = (MagicMock(), MagicMock())
        service_class.return_value.refresh.return_value = {
            "entries": [
                {"reviewable": True, "push_status": "not_started"},
                {"reviewable": False, "push_status": "not_started"},
            ]
        }

        with tempfile.TemporaryDirectory() as directory, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            state = Path(directory) / "review.json"
            result = main(["--refresh-only", "--state", str(state)])

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"entries": 2, "ready": 1, "state": str(state)},
        )
        service_class.return_value.refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
