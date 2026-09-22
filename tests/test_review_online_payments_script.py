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

    def test_html_offers_bank_line_suggestions_and_travel_categorization(self):
        self.assertIn("Other uncategorized bank lines", HTML)
        self.assertIn('id="bankRows"', HTML)
        self.assertIn("categorizeTravel", HTML)
        self.assertIn("/api/bank-lines/", HTML)
        self.assertIn("/categorize-travel", HTML)

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
    @patch("apps.payment_review.get_analytics_client")
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
    def test_refresh_only_updates_preview_and_exits(self, clients, analytics_factory, service_class):
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
            {"entries": 2, "ready": 1, "other_bank_lines": 0, "state": str(state)},
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

    def test_handler_routes_categorize_travel_expense(self):
        from apps.payment_review import make_handler

        service = MagicMock()
        service.categorize_travel_expense.return_value = {
            "transaction_id": "tx-123",
            "categorization_status": "categorized",
        }
        handler_cls = make_handler(service, "test-token")
        handler = handler_cls.__new__(handler_cls)
        body = json.dumps({"confirm": True}).encode("utf-8")
        handler.headers = {"X-Review-Token": "test-token", "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.path = "/api/bank-lines/tx-123/categorize-travel"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_POST()

        service.categorize_travel_expense.assert_called_once_with("tx-123")
        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["categorization_status"], "categorized")


if __name__ == "__main__":
    unittest.main()
