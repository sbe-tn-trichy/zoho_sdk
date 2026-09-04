import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.payment_review import HTML, _clients, main
from workflows.core.config import Config


class TestReviewOnlinePaymentsScript(unittest.TestCase):
    def test_html_offers_ambiguous_review_with_candidate_details(self):
        self.assertIn('<option value="ambiguous">Ambiguous</option>', HTML)
        self.assertIn("e.ambiguous_candidates", HTML)
        self.assertIn("matching bank lines", HTML)

    def test_html_offers_possible_match_review_with_candidate_details(self):
        self.assertIn('<option value="possible">Possible matches</option>', HTML)
        self.assertIn("e.possible_candidates", HTML)
        self.assertIn("reference differs", HTML)
        self.assertIn("selectPossibleCandidate", HTML)
        self.assertIn("allow_reference_override", HTML)

    @patch("apps.payment_review.get_books_client")
    @patch("apps.payment_review.get_creator_client")
    def test_clients_use_centralized_factories(self, creator_factory, books_factory):
        creator, books = _clients("http://token", "owner", "org", "in")

        self.assertIs(creator, creator_factory.return_value)
        self.assertIs(books, books_factory.return_value)
        creator_factory.assert_called_once_with(
            owner_name="owner", domain="in", token_url="http://token"
        )
        books_factory.assert_called_once_with(
            org_id="org", domain="in", token_url="http://token"
        )

    @patch("apps.payment_review.OnlinePaymentReviewService")
    @patch("apps.payment_review._clients")
    @patch.object(
        Config,
        "PAYMENT_CREATOR_REPORTS",
        {
            "online": "Configured_Online",
            "cheque": "Configured_Cheques",
            "cheque_detail": "Configured_Cheque_Details",
            "customer": "Configured_Customers",
            "checkpoint": "Configured_All_Payments",
        },
    )
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
        review_config = service_class.call_args.args[2]
        self.assertEqual(
            review_config.payment_reports,
            (("Online", "Configured_Online"), ("Cheque", "Configured_Cheques")),
        )
        self.assertEqual(
            review_config.cheque_detail_report_link_name,
            "Configured_Cheque_Details",
        )
        self.assertEqual(
            review_config.customer_report_link_name,
            "Configured_Customers",
        )
        self.assertEqual(
            review_config.creator_checkpoint_report_link_name,
            "Configured_All_Payments",
        )
        service_class.return_value.refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
