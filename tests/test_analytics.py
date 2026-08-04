import json
import unittest
from unittest.mock import MagicMock, patch

from zoho.analytics import ZohoAnalyticsAPI
from zoho.analytics.exceptions import ZohoAnalyticsError
from zoho.analytics.resources import Queries, Views


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

    def test_export_rejects_non_tabular_response_format(self):
        with self.assertRaisesRegex(ValueError, "structured row exports support"):
            Views(MagicMock()).export_data("workspace", "view", response_format="pdf")

    def test_bulk_export_decodes_json_rows(self):
        client = MagicMock()
        client.request.side_effect = [
            {"data": {"jobId": "job-json"}},
            {"data": {"jobStatus": "JOB COMPLETED", "downloadUrl": "https://download"}},
            b'{"data":[{"Customer":"Acme","Total":42}]}',
        ]

        rows = Views(client).export_bulk(
            "workspace",
            "view",
            poll_interval=0,
            response_format="json",
        )

        self.assertEqual(rows, [{"Customer": "Acme", "Total": 42}])

    @patch("requests.request")
    def test_rate_limit_error_exposes_status_and_retry_after(self, mock_request):
        response = MagicMock(status_code=429)
        response.headers = {"Retry-After": "12"}
        response.text = '{"data":{"errorCode":6045}}'
        mock_request.return_value = response
        client = ZohoAnalyticsAPI("token", "org")

        with self.assertRaises(ZohoAnalyticsError) as caught:
            client.metadata.list_folders("workspace")

        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.retry_after, "12")

    def test_dynamic_query_exports_and_decodes_json_rows(self):
        client = MagicMock()
        client.base_url = "https://analyticsapi.zoho.in/restapi/v2"
        client.request.side_effect = [
            {"data": {"jobId": "job-2"}},
            {
                "data": {
                    "jobCode": "1004",
                    "jobStatus": "JOB COMPLETED",
                    "downloadUrl": "https://download/query",
                }
            },
            [{"Customer Name": "Acme", "Amount": "100.00"}],
        ]

        query = 'SELECT * FROM "Payment Customer Finder" LIMIT 5'
        rows = Queries(client).execute("workspace", query, poll_interval=0)

        self.assertEqual(rows, [{"Customer Name": "Acme", "Amount": "100.00"}])
        create_call = client.request.call_args_list[0]
        self.assertEqual(create_call.args, ("GET", "bulk/workspaces/workspace/data"))
        sent_config = json.loads(create_call.kwargs["params"]["CONFIG"])
        self.assertEqual(sent_config["sqlQuery"], query)
        self.assertEqual(sent_config["responseFormat"], "json")
        self.assertTrue(sent_config["keyValueFormat"])

    def test_dynamic_query_rejects_empty_sql(self):
        with self.assertRaisesRegex(ValueError, "sql_query is required"):
            Queries(MagicMock()).execute("workspace", "  ")

    def test_dynamic_query_raises_when_job_fails(self):
        client = MagicMock()
        client.request.side_effect = [
            {"data": {"jobId": "job-3"}},
            {"data": {"jobCode": "1003", "jobStatus": "JOB FAILED"}},
        ]
        with self.assertRaises(ZohoAnalyticsError):
            Queries(client).execute("workspace", "SELECT 1", poll_interval=0)

    def test_client_exposes_queries_resource(self):
        client = ZohoAnalyticsAPI("token", "org")
        self.assertIsInstance(client.queries, Queries)


if __name__ == "__main__":
    unittest.main()
