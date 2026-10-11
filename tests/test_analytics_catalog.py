from unittest.mock import MagicMock, patch

import pytest

from workflows.analytics_catalog import AnalyticsCatalog, MetadataSyncError, WorkflowViewReference
from zoho.analytics import WorkspaceMetadataStore
from zoho.analytics.exceptions import ZohoAnalyticsError
from zoho.analytics.metadata import Metadata
from tests import test_analytics_metadata as _metadata_tests


def make_store(root):
    with WorkspaceMetadataStore(root / "metadata.sqlite", "w1") as store:
        store.replace_views("w1", [{"viewId": "t1", "viewName": "Base", "viewType": "Table"},
                                   {"viewId": "q1", "viewName": "Query", "viewType": "QueryTable"},
                                   {"viewId": "r1", "viewName": "Report", "viewType": "AnalysisView"}])
        store.set_info("last_successful_sync_at", "2026-10-11T09:00:00Z")


@pytest.mark.parametrize("version", ["3", "4"])
def test_migrate_preserves_metadata_and_backfills_sql(tmp_path, version):
    make_store(tmp_path)
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        store.put_view_details("t1", {"viewId": "t1"}, "1")
        store.connection.executescript("DROP VIEW views_with_workflows; DROP TABLE query_tables; DROP TABLE workflow_view_usage;")
        if version == "3":
            for column in ("source_modified_time", "details_synced_modified_time", "details_hash", "last_checked_at"):
                store.connection.execute(f"ALTER TABLE views DROP COLUMN {column}")
            for column in ("source_modified_time", "metadata_hash", "updated_at"):
                store.connection.execute(f"ALTER TABLE table_metadata DROP COLUMN {column}")
        store.set_info("schema_version", version)
        store.set_info("complete", True)
        store.set_info("updated_at", "old-sync")
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite", "w1") as store:
        assert store.get_info("schema_version") == "5"
        assert store.get_view_details("t1") == {"viewId": "t1"}
        assert store.get_info("last_successful_sync_at") == "old-sync"
        assert store.get_info("complete") == "False"
        assert not store.query_table_is_current("q1", "")


def test_exact_sql_and_workflow_preservation_and_deletion(tmp_path):
    make_store(tmp_path)
    sql = "SELECT 'â‚¹'\n FROM Base;  \n"
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        assert store.put_query_table("q1", {"sqlQuery": sql}, "1")
        assert not store.put_query_table("q1", {"sqlQuery": sql}, "2")
        assert store.get_query_table("q1")["sql_query"] == sql
        assert store.query_table_is_current("q1", "2")
        with pytest.raises(ValueError, match="sqlQuery"):
            store.put_query_table("q1", {"sqlQuery": ""})
        usage = {"workflow_key": "check", "view_id": "q1", "usage_type": "read", "source_file": "checker.py"}
        store.replace_workflow_usage([usage])
        assert store.connection.execute("SELECT used_by_workflows FROM views_with_workflows WHERE view_id='q1'").fetchone()[0] == "check"
        store.replace_views("w1", [])
        assert not store.get_query_table("q1")
        assert store.counts()["workflow_view_usage"] == 1


def test_transitive_impact_and_cycles(tmp_path):
    make_store(tmp_path)
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        store.replace_relationships([
            {"source": "view:q1", "target": "view:t1", "type": "view_uses_view"},
            {"source": "view:r1", "target": "view:q1", "type": "view_uses_view"},
            {"source": "view:q1", "target": "view:r1", "type": "view_uses_view"},
        ])
        store.replace_workflow_usage([
            {"workflow_key": key, "view_id": view, "usage_type": "read", "source_file": "checker.py"}
            for key, view in [("direct", "t1"), ("indirect", "r1")]])
        impact = store.workflow_impact("t1")
        assert [(r["workflow_key"], r["indirect"]) for r in impact] == [("direct", False), ("indirect", True)]


@patch("zoho.analytics.metadata._RequestController.pace")
def test_query_failure_retry_changed_and_missing_definitions(pace, tmp_path):
    client = _metadata_tests.TestAnalyticsMetadataDownloader._client()
    metadata = Metadata(client)
    original = client.request.side_effect
    failing = True
    modified = "1"
    sql = "SELECT 1\n"

    def request(method, endpoint, params=None):
        if endpoint == "workspaces/w1/querytables/t2":
            if failing:
                raise ZohoAnalyticsError("denied")
            return {"status": "success", "data": {"sqlQuery": sql, "involvedViews": [{"viewId": "t1"}]}}
        result = original(method, endpoint, params)
        if endpoint == "workspaces/w1/views":
            result["data"]["views"][1]["lastModifiedTime"] = modified
        return result

    client.request.side_effect = request
    assert not metadata.sync_workspace("w1", tmp_path, show_progress=False)["complete"]
    failing = False
    assert metadata.sync_workspace("w1", tmp_path, show_progress=False)["complete"]
    client.request.reset_mock()
    metadata.sync_workspace("w1", tmp_path, show_progress=False)
    assert "workspaces/w1/querytables/t2" not in [call.args[1] for call in client.request.call_args_list]
    sql, modified = "SELECT 2", "2"
    failing = True
    assert not metadata.sync_workspace("w1", tmp_path, show_progress=False)["complete"]
    failing = False
    assert metadata.sync_workspace("w1", tmp_path, show_progress=False)["complete"]
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        assert store.get_query_table("t2")["sql_query"] == "SELECT 2"
        assert store.get_info("last_successful_sync_at")
        assert any(r["target_id"] == "view:t1" for r in store.get_relationships("view:t2", "outgoing"))
        store.connection.execute("DELETE FROM query_tables")
        store.connection.commit()
    client.request.reset_mock()
    metadata.sync_workspace("w1", tmp_path, show_progress=False)
    assert "workspaces/w1/querytables/t2" in [call.args[1] for call in client.request.call_args_list]


def test_manual_sync_registers_references_then_analysis_uses_cache(tmp_path):
    make_store(tmp_path)
    client = MagicMock()
    client.metadata.sync_workspace.return_value = {"complete": True}
    catalog = AnalyticsCatalog(client, "w1", tmp_path, [
        WorkflowViewReference("check", "Query", "checker.py"),
        WorkflowViewReference("check", "Query", "checker.py", notes="Runtime override"),
        WorkflowViewReference("missing", "", "checker.py", view_id="deleted"),
        WorkflowViewReference("unresolved", "Unknown", "checker.py")])
    synced = catalog.sync()
    result = catalog.analyze("q1")
    client.metadata.sync_workspace.assert_called_once_with("w1", tmp_path)
    assert result["views"][0]["used_by_workflows"] == "check"
    assert len(synced["registry_issues"]) == 2
    assert result["workflow_impact"][0]["workflow_key"] == "check"
    assert result["workflow_impact"][0]["notes"] == "Runtime override"
    with pytest.raises(ValueError, match="Unknown view"):
        catalog.analyze("missing")


@pytest.mark.parametrize("raises", [False, True])
def test_catalog_rejects_failed_sync_before_returning_store(tmp_path, raises):
    make_store(tmp_path)
    client = MagicMock()
    if raises:
        client.metadata.sync_workspace.side_effect = RuntimeError("offline")
    else:
        client.metadata.sync_workspace.return_value = {"complete": False, "errors": ["denied"]}
    with pytest.raises(MetadataSyncError, match="last successful sync"):
        with AnalyticsCatalog(client, "w1", tmp_path).synchronized_store():
            pytest.fail("Analysis must not start")


def test_verify_update_forces_sql_readback_with_unchanged_timestamp(tmp_path):
    make_store(tmp_path)
    client = MagicMock()
    client.metadata.sync_workspace.return_value = {"complete": True}
    client.metadata.get_query_table.return_value = {"sqlQuery": "SELECT 2"}
    catalog = AnalyticsCatalog(client, "w1", tmp_path, [])
    catalog.verify_query_update("q1", "SELECT 2")
    assert [call[0] for call in client.metadata.method_calls] == ["get_query_table"]
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        assert store.get_query_table("q1")["sql_query"] == "SELECT 2"
    with pytest.raises(MetadataSyncError, match="differs"):
        catalog.verify_query_update("q1", "SELECT 3")


def test_cached_analysis_never_contacts_remote_and_exposes_freshness(tmp_path):
    make_store(tmp_path)
    client = MagicMock()
    client.metadata.sync_workspace.side_effect = AssertionError("Unexpected remote sync")
    catalog = AnalyticsCatalog(client, "w1", tmp_path, [])
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        store.set_info("complete", False)
    result = catalog.analyze()
    assert result["last_successful_sync_at"] == "2026-10-11T09:00:00Z"
    assert result["source"] == "cached_sqlite"
    assert result["sync"]["complete"] is False
    client.assert_not_called()
    assert not client.metadata.method_calls


@pytest.mark.parametrize("exists", [False, True])
def test_cached_analysis_requires_manual_initialization(tmp_path, exists):
    if exists:
        make_store(tmp_path)
        with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
            store.set_info("last_successful_sync_at", "")
    with pytest.raises(MetadataSyncError, match="--sync"):
        AnalyticsCatalog(None, "w1", tmp_path).analyze()
    if not exists:
        assert not (tmp_path / "metadata.sqlite").exists()


def test_verify_new_query_uses_targeted_requests_and_preserves_catalog_timestamp(tmp_path):
    make_store(tmp_path)
    client = MagicMock()
    client.metadata.get_query_table.return_value = {"sqlQuery": "SELECT 3"}
    client.metadata.get_view_details.return_value = {"viewId": "q2", "viewName": "New query"}
    catalog = AnalyticsCatalog(client, "w1", tmp_path, [
        WorkflowViewReference("new", "New query", "create.py", "create", "q2")])
    catalog.verify_query_update("q2", "SELECT 3")
    client.metadata.sync_workspace.assert_not_called()
    client.metadata.get_view_details.assert_called_once_with("q2")
    with WorkspaceMetadataStore(tmp_path / "metadata.sqlite") as store:
        assert store.get_query_table("q2")["sql_query"] == "SELECT 3"
        assert len(store.find_views()) == 4
        assert store.get_info("last_successful_sync_at") == "2026-10-11T09:00:00Z"
        assert store.workflow_impact("q2")[0]["workflow_key"] == "new"


def test_cli_default_uses_cache_without_authentication_and_writes_timestamp(tmp_path, monkeypatch):
    import sys
    from apps import analytics_metadata
    make_store(tmp_path)
    monkeypatch.setattr(sys, "argv", ["analytics_metadata", "--workspace-id", "w1", "--output", str(tmp_path)])
    with patch.object(analytics_metadata, "get_analytics_client") as factory:
        analytics_metadata.main()
        factory.assert_not_called()
    assert "2026-10-11T09:00:00Z" in (tmp_path / "analysis.md").read_text()
    assert "cached_sqlite" in (tmp_path / "analysis.json").read_text()
