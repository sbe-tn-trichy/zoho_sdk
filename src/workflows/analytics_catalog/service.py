"""Cached SQLite analysis with explicit manual metadata synchronization."""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence, TypedDict

from zoho.analytics import WorkspaceMetadataStore, WorkflowViewUsage
from .registry import DEFAULT_REFERENCES, WorkflowViewReference


class MetadataSyncError(RuntimeError):
    """Remote metadata could not be synchronized completely."""


class RegistryIssue(TypedDict):
    workflow_key: str
    reference: str
    reason: str


class AnalyticsCatalog:
    def __init__(self, analytics: Any, workspace_id: str,
                 output_dir: Path | None = None,
                 references: Sequence[WorkflowViewReference] = DEFAULT_REFERENCES):
        self.analytics = analytics
        self.workspace_id = workspace_id
        self.output_dir = output_dir or Path("output/analytics_metadata") / workspace_id
        self.references = tuple(references)

    def sync(self) -> dict[str, Any]:
        """Refresh remote metadata and replace the project registry atomically."""
        try:
            result = self.analytics.metadata.sync_workspace(self.workspace_id, self.output_dir)
        except Exception as exc:
            raise MetadataSyncError(f"Metadata sync failed: {exc}; last successful sync: {self._last_sync()}") from exc
        if not result.get("complete"):
            raise MetadataSyncError(f"Metadata sync incomplete: {result.get('errors', [])}; last successful sync: {self._last_sync()}")
        with WorkspaceMetadataStore(self.output_dir / "metadata.sqlite", self.workspace_id) as store:
            issues = self._refresh_registry(store)
            store.write_summary(self.output_dir / "summary.md")
            result["registry_issues"] = issues
            result["counts"] = store.counts()
        return result

    def _refresh_registry(self, store: WorkspaceMetadataStore) -> list[RegistryIssue]:
        rows: list[WorkflowViewUsage] = []
        issues: list[RegistryIssue] = []
        views = store.find_views()
        for ref in self.references:
            matches = [v for v in views if (v["view_id"] == ref.view_id if ref.view_id
                       else v["name"] == ref.view_name)]
            if len(matches) != 1:
                issues.append({"workflow_key": ref.workflow_key,
                               "reference": ref.view_id or ref.view_name,
                               "reason": "missing" if not matches else "ambiguous"})
                if not ref.view_id:
                    continue
            rows.append({"workflow_key": ref.workflow_key,
                         "view_id": ref.view_id or matches[0]["view_id"],
                         "usage_type": ref.usage_type, "source_file": ref.source_file, "notes": ref.notes})
        # Runtime registrations override defaults for the same consumer identity.
        store.replace_workflow_usage(list({
            (r["workflow_key"], r["view_id"], r["usage_type"], r["source_file"]): r
            for r in rows
        }.values()))
        return issues

    def _last_sync(self) -> str:
        path = self.output_dir / "metadata.sqlite"
        if not path.exists():
            return "never"
        with WorkspaceMetadataStore(path) as store:
            return store.get_info("last_successful_sync_at", "never") or "never"

    @contextmanager
    def cached_store(self) -> Iterator[WorkspaceMetadataStore]:
        """Read the existing catalog without remote requests or implicit creation."""
        path = self.output_dir / "metadata.sqlite"
        if not path.is_file():
            raise MetadataSyncError("No cached metadata. Run apps/analytics_metadata.py --sync first.")
        with WorkspaceMetadataStore(path, self.workspace_id) as store:
            if store.get_info("workspace_id") != self.workspace_id:
                raise MetadataSyncError("Cached metadata belongs to another workspace.")
            if store.get_info("last_successful_sync_at", "never") in {"", "never"}:
                raise MetadataSyncError("No successful metadata sync. Run apps/analytics_metadata.py --sync first.")
            yield store

    @contextmanager
    def synchronized_store(self) -> Iterator[WorkspaceMetadataStore]:
        """Explicit opt-in refresh followed by catalog access."""
        self.sync()
        with WorkspaceMetadataStore(self.output_dir / "metadata.sqlite", self.workspace_id) as store:
            yield store

    def analyze(self, view_id: str | None = None) -> dict[str, Any]:
        with self.cached_store() as store:
            sync = {"last_successful_sync_at": store.get_info("last_successful_sync_at"),
                    "complete": store.get_info("complete") == "True", "counts": store.counts()}
            views = [dict(r) for r in store.connection.execute(
                "SELECT view_id, name, view_type, used_by_workflows FROM views_with_workflows ORDER BY name")]
            if view_id:
                views = [v for v in views if v["view_id"] == view_id]
                if not views:
                    raise ValueError(f"Unknown view: {view_id}")
            return {"sync": sync, "last_successful_sync_at": sync["last_successful_sync_at"], "source": "cached_sqlite", "views": views,
                    "query_tables": [store.get_query_table(v["view_id"]) for v in views if v["view_type"].lower() in {"querytable", "query table"}],
                    "workflow_impact": store.workflow_impact(view_id) if view_id else []}

    def verify_query_update(self, view_id: str, expected_sql: str) -> None:
        """Force read-back even if Zoho's inventory timestamp has not advanced."""
        try:
            definition = self.analytics.metadata.get_query_table(self.workspace_id, view_id)
        except Exception as exc:
            raise MetadataSyncError(f"Cannot verify saved query table {view_id}: {exc}") from exc
        if definition.get("sqlQuery") != expected_sql:
            raise MetadataSyncError(f"Saved query table {view_id} differs from the requested SQL.")
        with self.cached_store() as store:
            views = {v["view_id"]: v for v in store.find_views()}
            if view_id not in views:
                details = self.analytics.metadata.get_view_details(view_id)
                with store.connection:
                    store.connection.execute(
                        "INSERT INTO views(view_id,workspace_id,name,view_type,raw_json) VALUES (?,?,?,?,?)",
                        (view_id, self.workspace_id, details.get("viewName", view_id), "QueryTable", json.dumps(details)))
                store.put_view_details(view_id, details)
            modified = store.connection.execute(
                "SELECT source_modified_time FROM views WHERE view_id = ?", (view_id,)).fetchone()[0]
            store.put_query_table(view_id, definition, modified)
            self._refresh_registry(store)
