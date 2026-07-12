import unittest
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

    def test_bulk_export_polls_and_decodes_csv(self):
        client = MagicMock()
        client.request.side_effect = [
            {"data": {"jobId": "job-1"}},
            {"data": {"jobStatus": "JOB COMPLETED", "downloadUrl": "https://download"}},
            b"Customer,Reference\nAcme,UTR1\n",
        ]
        rows = Views(client).export_bulk("workspace", "view", poll_interval=0)
        self.assertEqual(rows, [{"Customer": "Acme", "Reference": "UTR1"}])
        client.request.assert_any_call("GET", "", override_url="https://download")


if __name__ == "__main__":
    unittest.main()
