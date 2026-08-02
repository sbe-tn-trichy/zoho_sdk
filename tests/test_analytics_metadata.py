import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from zoho.analytics import ZohoAnalyticsAPI
from zoho.analytics.exceptions import ZohoAnalyticsError
from zoho.analytics.metadata import Metadata, _RequestController


def success(data):
    return {"status": "success", "data": data}


class TestAnalyticsMetadataEndpoints(unittest.TestCase):
    def test_view_listing_paginates_and_deduplicates(self):
        client = MagicMock()

        def request(method, endpoint, params=None):
            config = json.loads(params["CONFIG"])
            if config["startIndex"] == 1:
                return success({"views": [{"viewId": "1"}, {"viewId": "2"}]})
            return success({"views": [{"viewId": "2"}, {"viewId": "3"}]})

        client.request.side_effect = request
        views = Metadata(client).list_all_views("workspace", page_size=2)

        self.assertEqual([view["viewId"] for view in views], ["1", "2", "3"])
        # A full second page requires one final probe; duplicate IDs prevent a loop.
        self.assertEqual(client.request.call_count, 3)

    def test_workspace_and_view_details_are_unwrapped(self):
        client = MagicMock()
        client.request.side_effect = [
            success({"workspaces": {"workspaceId": "w1"}}),
            success({"views": {"viewId": "v1"}}),
        ]
        metadata = Metadata(client)

        self.assertEqual(metadata.get_workspace("w1"), {"workspaceId": "w1"})
        self.assertEqual(metadata.get_view_details("v1"), {"viewId": "v1"})
        config = json.loads(client.request.call_args.kwargs["params"]["CONFIG"])
        self.assertTrue(config["withInvolvedMetaInfo"])


class TestAnalyticsMetadataDownloader(unittest.TestCase):
    @staticmethod
    def _client():
        client = MagicMock()

        views = [
            {"viewId": "t1", "viewName": "Accounts", "viewType": "Table", "folderId": "f1"},
            {"viewId": "t2", "viewName": "Orders", "viewType": "QueryTable", "folderId": "f1"},
            {"viewId": "r1", "viewName": "Account Report", "viewType": "AnalysisView"},
        ]

        def request(method, endpoint, params=None):
            if endpoint == "workspaces/w1":
                return success({"workspaces": {"workspaceId": "w1", "workspaceName": "Demo"}})
            if endpoint == "workspaces/w1/folders":
                return success({"folders": [{"folderId": "f1", "folderName": "Tables"}]})
            if endpoint == "workspaces/w1/datasources":
                return success({
                    "dataSources": [{
                        "datasourceId": "ds1",
                        "datasourceName": "CRM",
                        "tableDetails": [{"viewId": "t1"}],
                    }]
                })
            if endpoint == "workspaces/w1/views":
                return success({"views": views})
            if endpoint == "views/r1":
                return success({
                    "views": {
                        "viewId": "r1",
                        "involvedMetaInfo": {"involvedViewIds": ["t1", "t2"]},
                    }
                })
            if endpoint.startswith("views/"):
                view_id = endpoint.split("/")[1]
                return success({"views": {"viewId": view_id}})
            if endpoint == "workspaces/w1/views/t1/metadata":
                return success({
                    "columns": [{"columnId": "c1", "columnName": "AccountID", "dataType": "PLAIN"}]
                })
            if endpoint == "workspaces/w1/views/t2/metadata":
                return success({
                    "columns": [{
                        "columnId": "c2",
                        "columnName": "AccountID",
                        "dataType": "PLAIN",
                        "pkTableName": "Accounts",
                        "pkColumnName": "AccountID",
                        "formulaDisplayName": "Normalized Account",
                    }]
                })
            if endpoint.endswith("columns/c1/dependents"):
                return success({"dependentViews": [{"viewId": "r1"}]})
            if endpoint.endswith("columns/c2/dependents"):
                return success({"dependentViews": []})
            raise AssertionError(f"Unexpected endpoint: {endpoint}")

        client.request.side_effect = request
        return client

    @patch("zoho.analytics.metadata._RequestController.pace")
    def test_download_writes_catalog_and_relationship_map(self, mock_pace):
        client = self._client()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Metadata(client).download_workspace(
                "w1",
                temp_dir,
                include_column_dependents=True,
                show_progress=False,
            )

            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["counts"]["views"], 3)
            self.assertTrue((Path(temp_dir) / "tables" / "t1.json").exists())
            relationships = json.loads(
                (Path(temp_dir) / "relationships.json").read_text(encoding="utf-8")
            )
            edge_types = {edge["type"] for edge in relationships["edges"]}
            self.assertIn("column_looks_up_column", edge_types)
            self.assertIn("datasource_feeds_view", edge_types)
            self.assertIn("view_uses_view", edge_types)
            self.assertIn("column_used_by_view", edge_types)
            self.assertIn("formula_defines_column", edge_types)

    @patch("zoho.analytics.metadata._RequestController.pace")
    def test_resume_skips_completed_view_and_table_requests(self, mock_pace):
        client = self._client()
        metadata = Metadata(client)
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata.download_workspace("w1", temp_dir, show_progress=False)
            client.request.reset_mock()
            metadata.download_workspace("w1", temp_dir, show_progress=False, resume=True)

            endpoints = [call.args[1] for call in client.request.call_args_list]
            self.assertNotIn("views/t1", endpoints)
            self.assertNotIn("workspaces/w1/views/t1/metadata", endpoints)

    @patch("zoho.analytics.metadata._RequestController.pace")
    def test_individual_view_failure_is_recorded_as_partial(self, mock_pace):
        client = self._client()
        original = client.request.side_effect

        def request(method, endpoint, params=None):
            if endpoint == "views/r1":
                raise ZohoAnalyticsError("permission denied")
            return original(method, endpoint, params=params)

        client.request.side_effect = request
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Metadata(client).download_workspace("w1", temp_dir, show_progress=False)

            self.assertFalse(manifest["complete"])
            self.assertEqual(manifest["counts"]["errors"], 1)
            self.assertEqual(manifest["errors"][0]["viewId"], "r1")


class TestAnalyticsMetadataRateLimits(unittest.TestCase):
    def test_rate_limit_is_printed_and_recovery_is_printed(self):
        client = MagicMock()
        client.request.side_effect = [
            ZohoAnalyticsError("errorCode 6045"),
            success({"folders": []}),
        ]
        metadata = Metadata(client)
        controller = _RequestController(
            requests_per_minute=50,
            max_retries=2,
            show_progress=True,
            sleep=MagicMock(),
            clock=MagicMock(return_value=0),
            jitter=lambda start, end: 0,
        )
        controller.pace = MagicMock()
        controller.progress = "84/230 views completed"
        metadata._controller = controller

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(metadata.list_folders("w1"), [])

        message = output.getvalue()
        self.assertIn("rate limit reached", message)
        self.assertIn("84/230 views completed", message)
        self.assertIn("API access resumed", message)
        controller.sleep.assert_called_once_with(15.0)

    def test_rate_limit_exhaustion_prints_pause_message(self):
        client = MagicMock()
        client.request.side_effect = ZohoAnalyticsError("HTTP Error: 429")
        metadata = Metadata(client)
        controller = _RequestController(
            requests_per_minute=50,
            max_retries=1,
            show_progress=True,
            sleep=MagicMock(),
            clock=MagicMock(return_value=0),
            jitter=lambda start, end: 0,
        )
        controller.pace = MagicMock()
        metadata._controller = controller

        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(ZohoAnalyticsError):
            metadata.list_folders("w1")

        self.assertIn("progress is saved and can be resumed", output.getvalue())


class TestAnalyticsTokenProviderFactory(unittest.TestCase):
    @patch("zoho.analytics.client.HttpTokenProvider")
    def test_factory_uses_local_analytics_connection_key(self, provider_class):
        provider_class.return_value.get_token.return_value = "analytics-token"

        client = ZohoAnalyticsAPI.from_token_provider(
            "http://localhost/tokens",
            organization_id="org1",
            domain="in",
        )

        provider_class.assert_called_once_with(
            "http://localhost/tokens",
            fallback_services={"zoho_analytics_conn": "analytics"},
        )
        provider_class.return_value.get_token.assert_called_once_with("zoho_analytics_conn")
        self.assertEqual(client.access_token, "analytics-token")
        self.assertIsInstance(client.metadata, Metadata)

    @patch("zoho.analytics.client.HttpTokenProvider")
    def test_factory_defaults_to_localhost_token_server(self, provider_class):
        provider_class.return_value.get_token.return_value = "analytics-token"

        ZohoAnalyticsAPI.from_token_provider(organization_id="org1", domain="in")

        provider_class.assert_called_once_with(
            "http://localhost:3000/server/new/tokens",
            fallback_services={"zoho_analytics_conn": "analytics"},
        )


if __name__ == "__main__":
    unittest.main()
