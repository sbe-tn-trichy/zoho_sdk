import unittest
from unittest.mock import MagicMock, patch

from scripts.review_online_payments import _clients


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


if __name__ == "__main__":
    unittest.main()
