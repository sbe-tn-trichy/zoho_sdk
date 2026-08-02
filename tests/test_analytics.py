import unittest
import json
from unittest.mock import MagicMock, patch

from zoho.analytics import ZohoAnalyticsAPI
from zoho.analytics.resources import Views


class TestZohoAnalyticsAPI(unittest.TestCase):
    @patch("requests.request")
    def test_request_adds_org_header(self, mock_request):
        response = MagicMock(status_code=200)
        response.headers = {"Content-Type": "application/json"}
        response.text = '{"data": []}'
        response.json.return_value = {"data": []}
        mock_request.return_value = response
        client = ZohoAnalyticsAPI("token", "org", domain="in")
        self.assertEqual(client.views.export_data("workspace", "view"), [])
        headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(headers["ZANALYTICS-ORGID"], "org")
        self.assertEqual(headers["Authorization"], "Zoho-oauthtoken token")
        config = json.loads(mock_request.call_args.kwargs["params"]["CONFIG"])
        self.assertEqual(config, {"responseFormat": "csv"})

    def test_bulk_export_polls_and_decodes_csv(self):
        client = MagicMock()
        client.request.side_effect = [
            {"data": {"jobId": "job-1"}},
            {"data": {"jobStatus": "JOB COMPLETED", "downloadUrl": "https://download"}},
            b"Customer,Reference\nAcme,UTR1\n",
        ]
        rows = Views(client).export_bulk("workspace", "view", poll_interval=0)
        self.assertEqual(rows, [{"Customer": "Acme", "Reference": "UTR1"}])
        create_call = client.request.call_args_list[0]
        self.assertEqual(create_call.args[:2], ("GET", "bulk/workspaces/workspace/views/view/data"))
        self.assertEqual(
            json.loads(create_call.kwargs["params"]["CONFIG"]),
            {"responseFormat": "csv"},
        )
        client.request.assert_any_call("GET", "", override_url="https://download")

    def test_dynamic_query_creates_job_and_returns_csv_rows(self):
        client = MagicMock()
        client.request.side_effect = [
            {"data": {"jobId": "job-2"}},
            {"data": {"jobStatus": "JOB COMPLETED", "downloadUrl": "https://download"}},
            b"Customer,Total\nAcme,42\n",
        ]

        rows = Views(client).query_data(
            "workspace",
            'SELECT "Customer", SUM("Sales") AS "Total" FROM "Sales" GROUP BY "Customer"',
            poll_interval=0,
        )

        self.assertEqual(rows, [{"Customer": "Acme", "Total": "42"}])
        create_call = client.request.call_args_list[0]
        self.assertEqual(create_call.args[:2], ("GET", "bulk/workspaces/workspace/data"))
        config = json.loads(create_call.kwargs["params"]["CONFIG"])
        self.assertEqual(config["responseFormat"], "csv")
        self.assertIn("SELECT", config["sqlQuery"])

    def test_dynamic_query_rejects_empty_sql(self):
        with self.assertRaisesRegex(ValueError, "sql_query is required"):
            Views(MagicMock()).query_data("workspace", "  ")


if __name__ == "__main__":
    unittest.main()
