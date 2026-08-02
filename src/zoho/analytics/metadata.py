import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .exceptions import ZohoAnalyticsError
from .snapshot import SCHEMA_VERSION, WorkspaceMetadataStore


logger = logging.getLogger("zoho.analytics.metadata")


_TABLE_VIEW_TYPES = {"table", "querytable", "query table"}
_RATE_LIMIT_PATTERN = re.compile(
    r"(?:\b429\b|\b6045\b|EXCEEDING_USR_PLN_API_FREQ_COUNT)",
    re.IGNORECASE,
)


def _json_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    return {"CONFIG": json.dumps(config or {})}


def _as_text(value: Any) -> str:
    return "" if value in (None, "null") else str(value)


def _data(payload: Any, key: Optional[str] = None) -> Any:
    if not isinstance(payload, dict):
        raise ZohoAnalyticsError("Analytics metadata API returned a non-object response.")
    if str(payload.get("status", "")).lower() == "failure":
        error_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        code = error_data.get("errorCode")
        message = error_data.get("errorMessage") or payload.get("summary") or "Metadata request failed."
        raise ZohoAnalyticsError(f"Analytics metadata error (code={code}): {message}")
    result = payload.get("data", {})
    if key is None:
        return result
    if not isinstance(result, dict):
        return []
    value = result.get(key, [])
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _iter_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _ids(value: Any, key: str) -> Set[str]:
    found: Set[str] = set()
    for item in _iter_dicts(value):
        candidate = item.get(key)
        if isinstance(candidate, list):
            found.update(
                str(entry) for entry in candidate if entry not in (None, "", "null")
            )
        elif candidate not in (None, "", "null"):
            found.add(str(candidate))
    return found


class _RequestController:
    def __init__(
        self,
        requests_per_minute: float,
        max_retries: int,
        show_progress: bool,
        sleep: Optional[Any] = None,
        clock: Optional[Any] = None,
        jitter: Optional[Any] = None,
    ):
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero.")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self.minimum_interval = 60.0 / requests_per_minute
        self.max_retries = max_retries
        self.show_progress = show_progress
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.jitter = jitter or random.uniform
        self.last_request_at: Optional[float] = None
        self.progress = ""

    def pace(self) -> None:
        if self.last_request_at is not None:
            remaining = self.minimum_interval - (self.clock() - self.last_request_at)
            if remaining > 0:
                self.sleep(remaining)
        self.last_request_at = self.clock()

    def retry_delay(self, error: Exception, retry_index: int) -> float:
        retry_after = getattr(error, "retry_after", None)
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return min(60.0, 15.0 * (2 ** retry_index)) + self.jitter(0.0, 1.0)

    def display(self, message: str) -> None:
        if self.show_progress:
            print(message, flush=True)

    def warning(self, message: str) -> None:
        logger.warning(message)
        self.display(message)


class Metadata:
    """Read-only Zoho Analytics metadata APIs and workspace snapshot collector."""

    def __init__(self, client: Any):
        self.client = client
        self._controller: Optional[_RequestController] = None

    @staticmethod
    def _is_rate_limit(error: Exception) -> bool:
        return getattr(error, "status_code", None) == 429 or bool(
            _RATE_LIMIT_PATTERN.search(str(error))
        )

    def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        controller = self._controller
        recovered_from_rate_limit = False
        retry_index = 0
        while True:
            if controller:
                controller.pace()
            try:
                payload = self.client.request("GET", endpoint, params=params)
                if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "failure":
                    error_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                    code = error_data.get("errorCode")
                    message = error_data.get("errorMessage") or payload.get("summary")
                    raise ZohoAnalyticsError(
                        f"Analytics metadata error (code={code}): {message or 'request failed'}"
                    )
            except ZohoAnalyticsError as exc:
                if not controller or not self._is_rate_limit(exc):
                    raise
                if retry_index >= controller.max_retries:
                    controller.warning(
                        "Zoho Analytics rate limit persisted after "
                        f"{controller.max_retries} retries. Metadata download paused; "
                        "progress is saved and can be resumed."
                    )
                    raise
                delay = controller.retry_delay(exc, retry_index)
                progress = f" Progress saved: {controller.progress}." if controller.progress else ""
                controller.warning(
                    "Zoho Analytics rate limit reached (6045/429). "
                    f"Retrying in {delay:.1f} seconds — retry "
                    f"{retry_index + 1}/{controller.max_retries}.{progress}"
                )
                controller.sleep(delay)
                retry_index += 1
                recovered_from_rate_limit = True
                continue
            if recovered_from_rate_limit and controller:
                controller.display(
                    "Zoho Analytics API access resumed. Continuing metadata download."
                )
            return payload

    def get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        workspace = _data(
            self._request(f"workspaces/{workspace_id}"),
            "workspaces",
        )
        return workspace if isinstance(workspace, dict) else {}

    def list_folders(self, workspace_id: str) -> List[Dict[str, Any]]:
        folders = _data(self._request(f"workspaces/{workspace_id}/folders"), "folders")
        return folders if isinstance(folders, list) else []

    def list_datasources(self, workspace_id: str) -> List[Dict[str, Any]]:
        sources = _data(
            self._request(f"workspaces/{workspace_id}/datasources"),
            "dataSources",
        )
        return sources if isinstance(sources, list) else []

    def list_all_views(
        self,
        workspace_id: str,
        page_size: int = 200,
        view_types: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        views: List[Dict[str, Any]] = []
        start_index = 1
        seen_ids: Set[str] = set()
        while True:
            config: Dict[str, Any] = {
                "startIndex": start_index,
                "noOfResult": page_size,
            }
            if view_types is not None:
                config["viewTypes"] = view_types
            page = _data(
                self._request(
                    f"workspaces/{workspace_id}/views",
                    params=_json_config(config),
                ),
                "views",
            )
            if not isinstance(page, list):
                page = []
            new_items = []
            for view in page:
                if not isinstance(view, dict):
                    continue
                view_id = str(view.get("viewId", ""))
                if view_id and view_id in seen_ids:
                    continue
                if view_id:
                    seen_ids.add(view_id)
                new_items.append(view)
            views.extend(new_items)
            if len(page) < page_size or not new_items:
                break
            start_index += len(page)
        return views

    def get_view_details(
        self,
        view_id: str,
        include_involved: bool = True,
    ) -> Dict[str, Any]:
        details = _data(
            self._request(
                f"views/{view_id}",
                params=_json_config({"withInvolvedMetaInfo": include_involved}),
            ),
            "views",
        )
        return details if isinstance(details, dict) else {}

    def get_table_metadata(self, workspace_id: str, view_id: str) -> Dict[str, Any]:
        return _data(
            self._request(f"workspaces/{workspace_id}/views/{view_id}/metadata")
        )

    def get_column_dependents(
        self,
        workspace_id: str,
        view_id: str,
        column_id: str,
    ) -> Dict[str, Any]:
        return _data(
            self._request(
                f"workspaces/{workspace_id}/views/{view_id}/columns/"
                f"{column_id}/dependents"
            )
        )

    def download_workspace(
        self,
        workspace_id: str,
        output_dir: Any,
        include_column_dependents: bool = False,
        requests_per_minute: float = 50,
        max_retries: int = 5,
        resume: bool = True,
        show_progress: bool = True,
        page_size: int = 200,
    ) -> Dict[str, Any]:
        """Download a resumable metadata snapshot into an indexed SQLite database."""
        if not workspace_id or not str(workspace_id).strip():
            raise ValueError("workspace_id is required.")
        root = Path(output_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        database_path = root / "metadata.sqlite"
        if not resume and database_path.exists():
            database_path.unlink()
        store = WorkspaceMetadataStore(database_path, str(workspace_id))
        previous_states = store.view_sync_states()
        completed_views = set(store.completed_ids("view"))
        completed_tables = set(store.completed_ids("table"))
        completed_dependents = set(store.completed_ids("dependent"))
        errors: List[Dict[str, Any]] = []
        manifest: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "workspaceId": str(workspace_id),
            "startedAt": store.get_info("started_at")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": "",
            "complete": False,
            "includeColumnDependents": include_column_dependents,
            "completedViewIds": sorted(completed_views),
            "completedTableIds": sorted(completed_tables),
            "completedDependentIds": sorted(completed_dependents),
            "errors": errors,
        }

        controller = _RequestController(
            requests_per_minute=requests_per_minute,
            max_retries=max_retries,
            show_progress=show_progress,
        )
        previous_controller = self._controller
        self._controller = controller

        def save_state() -> None:
            manifest["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            manifest["completedViewIds"] = sorted(completed_views)
            manifest["completedTableIds"] = sorted(completed_tables)
            manifest["completedDependentIds"] = sorted(completed_dependents)
            store.set_info("started_at", manifest["startedAt"])
            store.set_info("updated_at", manifest["updatedAt"])
            store.set_info("include_column_dependents", include_column_dependents)
            store.set_info("complete", manifest["complete"])
            store.replace_errors(errors)

        try:
            save_state()
            controller.display(f"Downloading metadata for workspace {workspace_id}...")
            workspace = self.get_workspace(workspace_id)
            folders = self.list_folders(workspace_id)
            datasources = self.list_datasources(workspace_id)
            views = self.list_all_views(workspace_id, page_size=page_size)
            current_ids = {
                str(view.get("viewId")) for view in views if view.get("viewId")
            }
            previous_ids = set(previous_states)
            modified_ids = {
                str(view["viewId"])
                for view in views
                if view.get("viewId")
                and str(view["viewId"]) in previous_states
                and _as_text(view.get("lastModifiedTime"))
                != previous_states[str(view["viewId"])]["source_modified_time"]
            }
            sync_counts = {
                "added": len(current_ids - previous_ids),
                "modified": len(modified_ids),
                "deleted": len(previous_ids - current_ids),
                "unchanged": len((current_ids & previous_ids) - modified_ids),
                "metadataWrites": 0,
            }
            store.put_workspace(workspace, str(workspace_id))
            store.replace_folders(str(workspace_id), folders)
            store.replace_datasources(str(workspace_id), datasources)
            store.replace_views(str(workspace_id), views)

            view_details: Dict[str, Dict[str, Any]] = {}
            table_metadata: Dict[str, Dict[str, Any]] = {}
            dependent_metadata: Dict[str, Dict[str, Any]] = {}
            table_views = [
                view for view in views
                if str(view.get("viewType", "")).strip().lower() in _TABLE_VIEW_TYPES
            ]

            for index, view in enumerate(views, start=1):
                view_id = str(view.get("viewId", ""))
                if not view_id:
                    errors.append({"operation": "view_details", "error": "View has no viewId."})
                    continue
                controller.progress = f"{index}/{len(views)} views completed"
                source_modified_time = _as_text(view.get("lastModifiedTime"))
                if resume and store.view_details_are_current(
                    view_id, source_modified_time
                ):
                    view_details[view_id] = store.get_view_details(view_id)
                    continue
                try:
                    details = self.get_view_details(view_id, include_involved=True)
                    view_details[view_id] = details
                    if store.put_view_details(view_id, details, source_modified_time):
                        sync_counts["metadataWrites"] += 1
                    completed_views.add(view_id)
                    save_state()
                except ZohoAnalyticsError as exc:
                    if self._is_rate_limit(exc):
                        save_state()
                        raise
                    errors.append({
                        "operation": "view_details",
                        "viewId": view_id,
                        "error": str(exc),
                    })

            for index, view in enumerate(table_views, start=1):
                view_id = str(view.get("viewId", ""))
                controller.progress = f"{index}/{len(table_views)} tables completed"
                source_modified_time = _as_text(view.get("lastModifiedTime"))
                if resume and store.table_metadata_is_current(
                    view_id, source_modified_time
                ):
                    table_metadata[view_id] = store.get_table_metadata(view_id)
                    continue
                try:
                    metadata = self.get_table_metadata(workspace_id, view_id)
                    table_metadata[view_id] = metadata
                    if store.put_table_metadata(view_id, metadata, source_modified_time):
                        sync_counts["metadataWrites"] += 1
                    completed_tables.add(view_id)
                    save_state()
                except ZohoAnalyticsError as exc:
                    if self._is_rate_limit(exc):
                        save_state()
                        raise
                    errors.append({
                        "operation": "table_metadata",
                        "viewId": view_id,
                        "error": str(exc),
                    })

            store.remove_table_metadata_except(
                str(view.get("viewId"))
                for view in table_views
                if view.get("viewId")
            )

            if include_column_dependents:
                columns = [
                    (view_id, column)
                    for view_id, metadata in table_metadata.items()
                    for column in metadata.get("columns", [])
                    if isinstance(column, dict) and column.get("columnId")
                ]
                for index, (view_id, column) in enumerate(columns, start=1):
                    column_id = str(column["columnId"])
                    dependent_id = f"{view_id}:{column_id}"
                    controller.progress = f"{index}/{len(columns)} columns completed"
                    if resume and dependent_id in completed_dependents:
                        dependent_metadata[dependent_id] = store.get_column_dependents(
                            view_id, column_id
                        )
                        continue
                    try:
                        dependents = self.get_column_dependents(
                            workspace_id,
                            view_id,
                            column_id,
                        )
                        dependent_metadata[dependent_id] = dependents
                        store.put_column_dependents(view_id, column_id, dependents)
                        completed_dependents.add(dependent_id)
                        save_state()
                    except ZohoAnalyticsError as exc:
                        if self._is_rate_limit(exc):
                            save_state()
                            raise
                        errors.append({
                            "operation": "column_dependents",
                            "viewId": view_id,
                            "columnId": column_id,
                            "error": str(exc),
                        })

            relationships = self._build_relationships(
                workspace_id,
                folders,
                datasources,
                views,
                view_details,
                table_metadata,
                dependent_metadata,
            )
            store.replace_relationships(relationships["edges"])
            store.replace_errors(errors)
            manifest["counts"] = store.counts()
            manifest["sync"] = sync_counts
            manifest["complete"] = not errors
            save_state()
            store.write_summary(root / "summary.md")
            store.optimize()
            controller.display(
                "Zoho Analytics metadata download completed: "
                f"{len(views)} views, {len(table_views)} tables, {len(errors)} errors."
            )
            return manifest
        finally:
            self._controller = previous_controller
            store.close()

    def sync_workspace(
        self,
        workspace_id: str,
        output_dir: Any,
        include_column_dependents: bool = False,
        requests_per_minute: float = 50,
        max_retries: int = 5,
        show_progress: bool = True,
        page_size: int = 200,
    ) -> Dict[str, Any]:
        """Incrementally refresh only new or modified workspace metadata."""
        return self.download_workspace(
            workspace_id=workspace_id,
            output_dir=output_dir,
            include_column_dependents=include_column_dependents,
            requests_per_minute=requests_per_minute,
            max_retries=max_retries,
            resume=True,
            show_progress=show_progress,
            page_size=page_size,
        )

    @staticmethod
    def migrate_json_snapshot(source_dir: Any, output_path: Optional[Any] = None) -> Dict[str, int]:
        """Convert a legacy expanded JSON snapshot to the indexed SQLite format."""
        root = Path(source_dir).expanduser().resolve()
        workspace = _read_json(root / "workspace.json", {})
        workspace_id = str(workspace.get("workspaceId") or "")
        if not workspace_id:
            raise ValueError("Legacy snapshot does not contain a workspaceId.")
        destination = (
            Path(output_path).expanduser().resolve()
            if output_path is not None
            else root / "metadata.sqlite"
        )
        if destination.exists():
            destination.unlink()
        folders = _read_json(root / "folders.json", [])
        datasources = _read_json(root / "datasources.json", [])
        views = _read_json(root / "views.json", [])
        manifest = _read_json(root / "manifest.json", {})
        errors = _read_json(root / "errors.json", manifest.get("errors", []))
        relationships = _read_json(root / "relationships.json", {"edges": []})

        with WorkspaceMetadataStore(destination, workspace_id) as store:
            store.put_workspace(workspace, workspace_id)
            store.replace_folders(workspace_id, folders)
            store.replace_datasources(workspace_id, datasources)
            store.replace_views(workspace_id, views)
            for view in views:
                view_id = str(view.get("viewId", ""))
                detail_path = root / "views" / (view_id + ".json")
                if view_id and detail_path.exists():
                    source_modified_time = _as_text(view.get("lastModifiedTime"))
                    store.put_view_details(
                        view_id, _read_json(detail_path, {}), source_modified_time
                    )
            table_dir = root / "tables"
            if table_dir.exists():
                for table_path in table_dir.glob("*.json"):
                    view = next(
                        (item for item in views if str(item.get("viewId")) == table_path.stem),
                        {},
                    )
                    store.put_table_metadata(
                        table_path.stem,
                        _read_json(table_path, {}),
                        _as_text(view.get("lastModifiedTime")),
                    )
            dependent_dir = root / "dependents"
            if dependent_dir.exists():
                for dependent_path in dependent_dir.glob("*.json"):
                    parts = dependent_path.stem.split("_", 1)
                    if len(parts) == 2:
                        store.put_column_dependents(
                            parts[0], parts[1], _read_json(dependent_path, {})
                        )
            store.replace_relationships(relationships.get("edges", []))
            store.replace_errors(errors)
            store.set_info("started_at", manifest.get("startedAt", ""))
            store.set_info("updated_at", manifest.get("updatedAt", ""))
            store.set_info("include_column_dependents", manifest.get("includeColumnDependents", False))
            store.set_info("complete", manifest.get("complete", not errors))
            store.write_summary(destination.parent / "summary.md")
            counts = store.counts()
            store.optimize()
            return counts

    @staticmethod
    def _build_catalog(
        workspace: Dict[str, Any],
        folders: List[Dict[str, Any]],
        datasources: List[Dict[str, Any]],
        views: List[Dict[str, Any]],
        view_details: Dict[str, Dict[str, Any]],
        table_metadata: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        catalog_views = []
        for view in views:
            item = dict(view)
            view_id = str(view.get("viewId", ""))
            if view_id in view_details:
                item["details"] = view_details[view_id]
            if view_id in table_metadata:
                item["columns"] = table_metadata[view_id].get("columns", [])
            catalog_views.append(item)
        return {
            "schemaVersion": 1,
            "workspace": workspace,
            "folders": folders,
            "datasources": datasources,
            "views": catalog_views,
        }

    @staticmethod
    def _build_relationships(
        workspace_id: str,
        folders: List[Dict[str, Any]],
        datasources: List[Dict[str, Any]],
        views: List[Dict[str, Any]],
        view_details: Dict[str, Dict[str, Any]],
        table_metadata: Dict[str, Dict[str, Any]],
        dependent_metadata: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = [
            {"id": f"workspace:{workspace_id}", "type": "workspace", "zohoId": workspace_id}
        ]
        edges: List[Dict[str, Any]] = []
        view_by_name: Dict[str, List[str]] = {}
        column_by_name: Dict[str, Dict[str, List[str]]] = {}

        for folder in folders:
            folder_id = str(folder.get("folderId", ""))
            if not folder_id:
                continue
            nodes.append({
                "id": f"folder:{folder_id}",
                "type": "folder",
                "zohoId": folder_id,
                "name": folder.get("folderName", ""),
            })
            edges.append({
                "type": "workspace_contains_folder",
                "source": f"workspace:{workspace_id}",
                "target": f"folder:{folder_id}",
            })

        for view in views:
            view_id = str(view.get("viewId", ""))
            if not view_id:
                continue
            name = str(view.get("viewName", ""))
            if name:
                view_by_name.setdefault(name.lower(), []).append(view_id)
            nodes.append({
                "id": f"view:{view_id}",
                "type": "view",
                "viewType": view.get("viewType", ""),
                "zohoId": view_id,
                "name": name,
            })
            folder_id = str(view.get("folderId", ""))
            if folder_id and folder_id != "null":
                edges.append({
                    "type": "folder_contains_view",
                    "source": f"folder:{folder_id}",
                    "target": f"view:{view_id}",
                })
            else:
                edges.append({
                    "type": "workspace_contains_view",
                    "source": f"workspace:{workspace_id}",
                    "target": f"view:{view_id}",
                })
            parent_id = str(view.get("parentViewId", ""))
            if parent_id and parent_id != "null":
                edges.append({
                    "type": "view_parent",
                    "source": f"view:{view_id}",
                    "target": f"view:{parent_id}",
                })

        for view_id, metadata in table_metadata.items():
            names: Dict[str, List[str]] = {}
            for column in metadata.get("columns", []):
                if not isinstance(column, dict) or not column.get("columnId"):
                    continue
                column_id = str(column["columnId"])
                column_name = str(column.get("columnName", ""))
                if column_name:
                    names.setdefault(column_name.lower(), []).append(column_id)
                nodes.append({
                    "id": f"column:{column_id}",
                    "type": "column",
                    "zohoId": column_id,
                    "name": column_name,
                    "dataType": column.get("dataType"),
                    "viewId": view_id,
                })
                edges.append({
                    "type": "view_contains_column",
                    "source": f"view:{view_id}",
                    "target": f"column:{column_id}",
                })
                formula_name = str(column.get("formulaDisplayName", "")).strip()
                if formula_name:
                    nodes.append({
                        "id": f"formula:{column_id}",
                        "type": "formula",
                        "name": formula_name,
                        "columnId": column_id,
                        "viewId": view_id,
                    })
                    edges.append({
                        "type": "formula_defines_column",
                        "source": f"formula:{column_id}",
                        "target": f"column:{column_id}",
                    })
            column_by_name[view_id] = names

        for view_id, metadata in table_metadata.items():
            for column in metadata.get("columns", []):
                if not isinstance(column, dict) or not column.get("columnId"):
                    continue
                table_name = str(column.get("pkTableName", "")).strip()
                target_column_name = str(column.get("pkColumnName", "")).strip()
                if not table_name or not target_column_name:
                    continue
                target_view_ids = view_by_name.get(table_name.lower(), [])
                target_view_id = target_view_ids[0] if len(target_view_ids) == 1 else None
                target_column_ids = (
                    column_by_name.get(target_view_id, {}).get(target_column_name.lower(), [])
                    if target_view_id else []
                )
                target_column_id = target_column_ids[0] if len(target_column_ids) == 1 else None
                edge = {
                    "type": "column_looks_up_column",
                    "source": f"column:{column['columnId']}",
                    "targetTableName": table_name,
                    "targetColumnName": target_column_name,
                    "resolved": bool(target_column_id),
                }
                if target_column_id:
                    edge["target"] = f"column:{target_column_id}"
                edges.append(edge)

        for source_view_id, details in view_details.items():
            involved = (
                _ids(details, "involvedViewId")
                | _ids(details, "involvedViewIds")
                | _ids(details.get("involvedMetaInfo", {}), "viewId")
                | _ids(details.get("involvedViews", []), "viewId")
            )
            for target_view_id in involved:
                if target_view_id != source_view_id:
                    edges.append({
                        "type": "view_uses_view",
                        "source": f"view:{source_view_id}",
                        "target": f"view:{target_view_id}",
                    })

        for source_id, dependents in dependent_metadata.items():
            _, column_id = source_id.split(":", 1)
            for target_view_id in _ids(dependents, "viewId"):
                edges.append({
                    "type": "column_used_by_view",
                    "source": f"column:{column_id}",
                    "target": f"view:{target_view_id}",
                })

        for datasource in datasources:
            datasource_id = str(
                datasource.get("datasourceId")
                or datasource.get("datasourceName")
                or datasource.get("source")
                or ""
            )
            if not datasource_id:
                continue
            nodes.append({
                "id": f"datasource:{datasource_id}",
                "type": "datasource",
                "zohoId": datasource.get("datasourceId"),
                "name": datasource.get("datasourceName", ""),
            })
            for target_view_id in _ids(datasource, "viewId"):
                edges.append({
                    "type": "datasource_feeds_view",
                    "source": f"datasource:{datasource_id}",
                    "target": f"view:{target_view_id}",
                })

        unique_edges: List[Dict[str, Any]] = []
        seen_edges: Set[str] = set()
        for edge in edges:
            marker = json.dumps(edge, sort_keys=True)
            if marker not in seen_edges:
                seen_edges.add(marker)
                unique_edges.append(edge)
        return {"schemaVersion": 1, "nodes": nodes, "edges": unique_edges}


__all__ = ["Metadata"]
