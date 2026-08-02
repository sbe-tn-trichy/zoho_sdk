import hashlib
import json
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 4


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pack_json(value: Any) -> bytes:
    return zlib.compress(_compact_json(value).encode("utf-8"), level=9)


def _unpack_json(value: Any) -> Any:
    if isinstance(value, bytes):
        return json.loads(zlib.decompress(value).decode("utf-8"))
    return json.loads(value)


def _text(value: Any) -> str:
    return "" if value in (None, "null") else str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_compact_json(value).encode("utf-8")).hexdigest()


class WorkspaceMetadataStore:
    """Indexed, single-file storage for a Zoho Analytics workspace snapshot."""

    def __init__(self, path: Any, workspace_id: Optional[str] = None):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if exists:
            try:
                version = self.get_info("schema_version")
            except sqlite3.OperationalError:
                self.close()
                raise ValueError("File is not a Zoho Analytics metadata database.")
            if version == "3" and workspace_id:
                self._upgrade_v3_to_v4()
                version = str(SCHEMA_VERSION)
            if version != str(SCHEMA_VERSION):
                self.close()
                raise ValueError(
                    "Unsupported metadata schema version %r; expected %s."
                    % (version, SCHEMA_VERSION)
                )
        else:
            self.connection.execute("PRAGMA journal_mode = DELETE")
            self.connection.execute("PRAGMA synchronous = NORMAL")
            self._create_schema()
        if workspace_id:
            existing = self.get_info("workspace_id")
            if existing and existing != str(workspace_id):
                self.close()
                raise ValueError("Existing metadata database belongs to a different workspace.")
            if not existing:
                self.set_info("workspace_id", str(workspace_id))

    def _upgrade_v3_to_v4(self) -> None:
        """Upgrade the first SQLite snapshot format before an incremental write."""
        with self.connection:
            self.connection.executescript(
                """
                ALTER TABLE views ADD COLUMN source_modified_time TEXT NOT NULL DEFAULT '';
                ALTER TABLE views ADD COLUMN details_synced_modified_time TEXT NOT NULL DEFAULT '';
                ALTER TABLE views ADD COLUMN details_hash TEXT NOT NULL DEFAULT '';
                ALTER TABLE views ADD COLUMN last_checked_at TEXT NOT NULL DEFAULT '';
                ALTER TABLE table_metadata ADD COLUMN source_modified_time TEXT NOT NULL DEFAULT '';
                ALTER TABLE table_metadata ADD COLUMN metadata_hash TEXT NOT NULL DEFAULT '';
                ALTER TABLE table_metadata ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
                """
            )
            view_rows = self.connection.execute(
                "SELECT view_id, raw_json, details_json FROM views"
            ).fetchall()
            modified_times: Dict[str, str] = {}
            for row in view_rows:
                modified_time = _text(_unpack_json(row["raw_json"]).get("lastModifiedTime"))
                modified_times[row["view_id"]] = modified_time
                details_hash = (
                    _json_hash(_unpack_json(row["details_json"]))
                    if row["details_json"] is not None
                    else ""
                )
                self.connection.execute(
                    """
                    UPDATE views
                    SET source_modified_time = ?,
                        details_synced_modified_time = ?, details_hash = ?
                    WHERE view_id = ?
                    """,
                    (modified_time, modified_time, details_hash, row["view_id"]),
                )
            for row in self.connection.execute(
                "SELECT view_id, raw_json FROM table_metadata"
            ).fetchall():
                self.connection.execute(
                    """
                    UPDATE table_metadata
                    SET source_modified_time = ?, metadata_hash = ?, updated_at = ?
                    WHERE view_id = ?
                    """,
                    (
                        modified_times.get(row["view_id"], ""),
                        _json_hash(_unpack_json(row["raw_json"])),
                        _utc_now(),
                        row["view_id"],
                    ),
                )
            self.connection.execute(
                "UPDATE snapshot_info SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )

    def __enter__(self) -> "WorkspaceMetadataStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshot_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                workspace_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS folders (
                folder_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS datasources (
                datasource_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS views (
                view_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                folder_id TEXT,
                parent_view_id TEXT,
                name TEXT NOT NULL DEFAULT '',
                view_type TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL,
                details_json TEXT,
                source_modified_time TEXT NOT NULL DEFAULT '',
                details_synced_modified_time TEXT NOT NULL DEFAULT '',
                details_hash TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS columns (
                column_id TEXT PRIMARY KEY,
                view_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                data_type TEXT NOT NULL DEFAULT '',
                formula_name TEXT NOT NULL DEFAULT '',
                lookup_table_name TEXT NOT NULL DEFAULT '',
                lookup_column_name TEXT NOT NULL DEFAULT '',
                ordinal INTEGER,
                raw_json TEXT NOT NULL,
                FOREIGN KEY(view_id) REFERENCES views(view_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS table_metadata (
                view_id TEXT PRIMARY KEY,
                raw_json TEXT NOT NULL,
                source_modified_time TEXT NOT NULL DEFAULT '',
                metadata_hash TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(view_id) REFERENCES views(view_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS column_dependents (
                view_id TEXT NOT NULL,
                column_id TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                PRIMARY KEY(view_id, column_id)
            );
            CREATE TABLE IF NOT EXISTS entities (
                entity_id INTEGER PRIMARY KEY,
                entity_key TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS relationships (
                source_entity_id INTEGER NOT NULL,
                target_entity_id INTEGER NOT NULL DEFAULT 0,
                relationship_type TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 1,
                target_table_name TEXT NOT NULL DEFAULT '',
                target_column_name TEXT NOT NULL DEFAULT '',
                extra_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(
                    source_entity_id, target_entity_id, relationship_type,
                    target_table_name, target_column_name
                )
            );
            CREATE TABLE IF NOT EXISTS download_progress (
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                PRIMARY KEY(object_type, object_id)
            );
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                view_id TEXT,
                column_id TEXT,
                message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_views_name ON views(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_views_type ON views(view_type);
            CREATE INDEX IF NOT EXISTS idx_views_folder ON views(folder_id);
            CREATE INDEX IF NOT EXISTS idx_columns_view ON columns(view_id);
            CREATE INDEX IF NOT EXISTS idx_columns_name ON columns(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_relationship_source ON relationships(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_relationship_target ON relationships(target_entity_id);
            CREATE INDEX IF NOT EXISTS idx_relationship_type ON relationships(relationship_type);
            """
        )
        self.set_info("schema_version", str(SCHEMA_VERSION))

    def set_info(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO snapshot_info(key, value) VALUES (?, ?)",
            (key, _text(value)),
        )
        self.connection.commit()

    def get_info(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.connection.execute(
            "SELECT value FROM snapshot_info WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def put_workspace(self, workspace: Dict[str, Any], workspace_id: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO workspaces(workspace_id, name, raw_json) VALUES (?, ?, ?)",
            (
                str(workspace.get("workspaceId") or workspace_id),
                _text(workspace.get("workspaceName")),
                _pack_json(workspace),
            ),
        )
        self.connection.commit()

    def replace_folders(self, workspace_id: str, folders: Iterable[Dict[str, Any]]) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM folders WHERE workspace_id = ?", (workspace_id,))
            self.connection.executemany(
                "INSERT INTO folders(folder_id, workspace_id, name, raw_json) VALUES (?, ?, ?, ?)",
                [
                    (
                        str(item["folderId"]),
                        workspace_id,
                        _text(item.get("folderName")),
                        _pack_json(item),
                    )
                    for item in folders
                    if item.get("folderId")
                ],
            )

    def replace_datasources(
        self, workspace_id: str, datasources: Iterable[Dict[str, Any]]
    ) -> None:
        rows = []
        for item in datasources:
            datasource_id = item.get("datasourceId") or item.get("datasourceName") or item.get("source")
            if datasource_id:
                rows.append(
                    (
                        str(datasource_id),
                        workspace_id,
                        _text(item.get("datasourceName")),
                        _pack_json(item),
                    )
                )
        with self.connection:
            self.connection.execute(
                "DELETE FROM datasources WHERE workspace_id = ?", (workspace_id,)
            )
            self.connection.executemany(
                "INSERT INTO datasources(datasource_id, workspace_id, name, raw_json) VALUES (?, ?, ?, ?)",
                rows,
            )

    def replace_views(self, workspace_id: str, views: Iterable[Dict[str, Any]]) -> None:
        views = list(views)
        current_ids = [str(item["viewId"]) for item in views if item.get("viewId")]
        existing_ids = {
            row["view_id"]
            for row in self.connection.execute(
                "SELECT view_id FROM views WHERE workspace_id = ?", (workspace_id,)
            )
        }
        removed_ids = existing_ids - set(current_ids)
        with self.connection:
            if current_ids:
                placeholders = ",".join("?" for _ in current_ids)
                self.connection.execute(
                    "DELETE FROM views WHERE workspace_id = ? AND view_id NOT IN (%s)"
                    % placeholders,
                    [workspace_id] + current_ids,
                )
            else:
                self.connection.execute(
                    "DELETE FROM views WHERE workspace_id = ?", (workspace_id,)
                )
            for view_id in removed_ids:
                self.connection.execute(
                    "DELETE FROM download_progress WHERE object_type IN ('view', 'table') AND object_id = ?",
                    (view_id,),
                )
                self.connection.execute(
                    "DELETE FROM download_progress WHERE object_type = 'dependent' AND object_id LIKE ?",
                    (view_id + ":%",),
                )
                self.connection.execute(
                    "DELETE FROM column_dependents WHERE view_id = ?", (view_id,)
                )
            for item in views:
                view_id = item.get("viewId")
                if not view_id:
                    continue
                self.connection.execute(
                    """
                    INSERT INTO views(
                        view_id, workspace_id, folder_id, parent_view_id,
                        name, view_type, raw_json, details_json,
                        source_modified_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    ON CONFLICT(view_id) DO UPDATE SET
                        workspace_id=excluded.workspace_id,
                        folder_id=excluded.folder_id,
                        parent_view_id=excluded.parent_view_id,
                        name=excluded.name,
                        view_type=excluded.view_type,
                        raw_json=excluded.raw_json,
                        source_modified_time=excluded.source_modified_time
                    """,
                    (
                        str(view_id),
                        workspace_id,
                        _text(item.get("folderId")) or None,
                        _text(item.get("parentViewId")) or None,
                        _text(item.get("viewName")),
                        _text(item.get("viewType")),
                        _pack_json(item),
                        _text(item.get("lastModifiedTime")),
                    ),
                )

    def put_view_details(
        self,
        view_id: str,
        details: Dict[str, Any],
        source_modified_time: str = "",
    ) -> bool:
        content_hash = _json_hash(details)
        existing = self.connection.execute(
            "SELECT details_hash FROM views WHERE view_id = ?", (view_id,)
        ).fetchone()
        changed = not existing or existing["details_hash"] != content_hash
        with self.connection:
            if changed:
                self.connection.execute(
                    "UPDATE views SET details_json = ?, details_hash = ? WHERE view_id = ?",
                    (_pack_json(details), content_hash, view_id),
                )
            self.connection.execute(
                """
                UPDATE views
                SET details_synced_modified_time = ?, last_checked_at = ?
                WHERE view_id = ?
                """,
                (source_modified_time, _utc_now(), view_id),
            )
            self._mark_completed("view", view_id)
        return changed

    def get_view_details(self, view_id: str) -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT details_json FROM views WHERE view_id = ?", (view_id,)
        ).fetchone()
        return _unpack_json(row["details_json"]) if row and row["details_json"] else {}

    def view_details_are_current(self, view_id: str, source_modified_time: str) -> bool:
        row = self.connection.execute(
            "SELECT details_json, details_synced_modified_time FROM views WHERE view_id = ?",
            (view_id,),
        ).fetchone()
        return bool(
            row
            and row["details_json"] is not None
            and row["details_synced_modified_time"] == source_modified_time
            and self.is_completed("view", view_id)
        )

    def put_table_metadata(
        self,
        view_id: str,
        metadata: Dict[str, Any],
        source_modified_time: str = "",
    ) -> bool:
        content_hash = _json_hash(metadata)
        existing = self.connection.execute(
            "SELECT metadata_hash FROM table_metadata WHERE view_id = ?", (view_id,)
        ).fetchone()
        changed = not existing or existing["metadata_hash"] != content_hash
        rows = []
        for index, column in enumerate(metadata.get("columns", [])):
            if not isinstance(column, dict) or not column.get("columnId"):
                continue
            rows.append(
                (
                    str(column["columnId"]),
                    view_id,
                    _text(column.get("columnName")),
                    _text(column.get("dataType")),
                    _text(column.get("formulaDisplayName")),
                    _text(column.get("pkTableName")),
                    _text(column.get("pkColumnName")),
                    column.get("columnIndex", index),
                    _pack_json(column),
                )
            )
        with self.connection:
            if changed:
                self.connection.execute("DELETE FROM columns WHERE view_id = ?", (view_id,))
                self.connection.executemany(
                    """
                    INSERT INTO columns(
                        column_id, view_id, name, data_type, formula_name,
                        lookup_table_name, lookup_column_name, ordinal, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            self.connection.execute(
                """
                INSERT INTO table_metadata(
                    view_id, raw_json, source_modified_time, metadata_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(view_id) DO UPDATE SET
                    raw_json=CASE WHEN metadata_hash != excluded.metadata_hash
                                  THEN excluded.raw_json ELSE raw_json END,
                    source_modified_time=excluded.source_modified_time,
                    metadata_hash=excluded.metadata_hash,
                    updated_at=excluded.updated_at
                """,
                (view_id, _pack_json(metadata), source_modified_time, content_hash, _utc_now()),
            )
            self._mark_completed("table", view_id)
        return changed

    def get_table_metadata(self, view_id: str) -> Dict[str, Any]:
        metadata_row = self.connection.execute(
            "SELECT raw_json FROM table_metadata WHERE view_id = ?", (view_id,)
        ).fetchone()
        if metadata_row:
            return _unpack_json(metadata_row["raw_json"])
        rows = self.connection.execute(
            "SELECT raw_json FROM columns WHERE view_id = ? ORDER BY ordinal, column_id",
            (view_id,),
        ).fetchall()
        return {"columns": [_unpack_json(row["raw_json"]) for row in rows]}

    def table_metadata_is_current(self, view_id: str, source_modified_time: str) -> bool:
        row = self.connection.execute(
            "SELECT source_modified_time FROM table_metadata WHERE view_id = ?",
            (view_id,),
        ).fetchone()
        return bool(
            row
            and row["source_modified_time"] == source_modified_time
            and self.is_completed("table", view_id)
        )

    def view_sync_states(self) -> Dict[str, Dict[str, str]]:
        return {
            row["view_id"]: dict(row)
            for row in self.connection.execute(
                """
                SELECT view_id, source_modified_time,
                       details_synced_modified_time, details_hash
                FROM views
                """
            )
        }

    def remove_table_metadata_except(self, view_ids: Iterable[str]) -> None:
        view_ids = list(view_ids)
        with self.connection:
            if view_ids:
                placeholders = ",".join("?" for _ in view_ids)
                self.connection.execute(
                    "DELETE FROM table_metadata WHERE view_id NOT IN (%s)" % placeholders,
                    view_ids,
                )
                self.connection.execute(
                    "DELETE FROM columns WHERE view_id NOT IN (%s)" % placeholders,
                    view_ids,
                )
                self.connection.execute(
                    "DELETE FROM column_dependents WHERE view_id NOT IN (%s)" % placeholders,
                    view_ids,
                )
            else:
                self.connection.execute("DELETE FROM table_metadata")
                self.connection.execute("DELETE FROM columns")
                self.connection.execute("DELETE FROM column_dependents")

    def put_column_dependents(
        self, view_id: str, column_id: str, dependents: Dict[str, Any]
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO column_dependents(view_id, column_id, raw_json) VALUES (?, ?, ?)",
                (view_id, column_id, _pack_json(dependents)),
            )
            self._mark_completed("dependent", "%s:%s" % (view_id, column_id))

    def get_column_dependents(self, view_id: str, column_id: str) -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT raw_json FROM column_dependents WHERE view_id = ? AND column_id = ?",
            (view_id, column_id),
        ).fetchone()
        return _unpack_json(row["raw_json"]) if row else {}

    def _mark_completed(self, object_type: str, object_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO download_progress(object_type, object_id) VALUES (?, ?)",
            (object_type, object_id),
        )

    def is_completed(self, object_type: str, object_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM download_progress WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        ).fetchone() is not None

    def completed_ids(self, object_type: str) -> List[str]:
        return [
            row["object_id"]
            for row in self.connection.execute(
                "SELECT object_id FROM download_progress WHERE object_type = ? ORDER BY object_id",
                (object_type,),
            )
        ]

    def replace_relationships(self, edges: Iterable[Dict[str, Any]]) -> None:
        edges = list(edges)
        entity_keys = sorted(
            {
                _text(edge.get(key))
                for edge in edges
                for key in ("source", "target")
                if _text(edge.get(key))
            }
        )
        with self.connection:
            self.connection.execute("DELETE FROM relationships")
            self.connection.execute("DELETE FROM entities")
            self.connection.executemany(
                "INSERT INTO entities(entity_key) VALUES (?)",
                [(key,) for key in entity_keys],
            )
        entity_ids = {
            row["entity_key"]: row["entity_id"]
            for row in self.connection.execute("SELECT entity_id, entity_key FROM entities")
        }
        rows = []
        for edge in edges:
            known = {
                "source", "target", "type", "resolved",
                "targetTableName", "targetColumnName",
            }
            extra = {key: value for key, value in edge.items() if key not in known}
            rows.append(
                (
                    entity_ids[_text(edge.get("source"))],
                    entity_ids.get(_text(edge.get("target")), 0),
                    _text(edge.get("type")),
                    1 if edge.get("resolved", True) else 0,
                    _text(edge.get("targetTableName")),
                    _text(edge.get("targetColumnName")),
                    _compact_json(extra),
                )
            )
        with self.connection:
            self.connection.execute("DELETE FROM relationships")
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO relationships(
                    source_entity_id, target_entity_id, relationship_type, resolved,
                    target_table_name, target_column_name, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def replace_errors(self, errors: Iterable[Dict[str, Any]]) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM errors")
            self.connection.executemany(
                "INSERT INTO errors(operation, view_id, column_id, message) VALUES (?, ?, ?, ?)",
                [
                    (
                        _text(error.get("operation")),
                        _text(error.get("viewId")) or None,
                        _text(error.get("columnId")) or None,
                        _text(error.get("error")),
                    )
                    for error in errors
                ],
            )

    def find_views(
        self, name: Optional[str] = None, view_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        clauses = []
        parameters: List[Any] = []
        if name:
            clauses.append("name LIKE ? COLLATE NOCASE")
            parameters.append("%%%s%%" % name)
        if view_type:
            clauses.append("view_type = ? COLLATE NOCASE")
            parameters.append(view_type)
        sql = "SELECT view_id, name, view_type, folder_id, parent_view_id FROM views"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name, view_id"
        return [dict(row) for row in self.connection.execute(sql, parameters)]

    def get_columns(self, view_id: str) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT column_id, name, data_type, formula_name,
                       lookup_table_name, lookup_column_name, ordinal
                FROM columns WHERE view_id = ? ORDER BY ordinal, column_id
                """,
                (view_id,),
            )
        ]

    def get_relationships(
        self, entity_id: str, direction: str = "both"
    ) -> List[Dict[str, Any]]:
        if direction not in {"both", "incoming", "outgoing"}:
            raise ValueError("direction must be 'both', 'incoming', or 'outgoing'.")
        if direction == "incoming":
            where = "target.entity_key = ?"
            parameters = (entity_id,)
        elif direction == "outgoing":
            where = "source.entity_key = ?"
            parameters = (entity_id,)
        else:
            where = "source.entity_key = ? OR target.entity_key = ?"
            parameters = (entity_id, entity_id)
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT source.entity_key AS source_id,
                       COALESCE(target.entity_key, '') AS target_id,
                       r.relationship_type, r.resolved,
                       r.target_table_name, r.target_column_name, r.extra_json
                FROM relationships r
                JOIN entities source ON source.entity_id = r.source_entity_id
                LEFT JOIN entities target ON target.entity_id = r.target_entity_id
                WHERE %s
                ORDER BY r.relationship_type, source.entity_key, target.entity_key
                """ % where,
                parameters,
            )
        ]

    def counts(self) -> Dict[str, int]:
        result = {}
        for name in ("folders", "datasources", "views", "columns", "relationships", "errors"):
            result[name] = int(
                self.connection.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
            )
        result["tables"] = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM views WHERE lower(view_type) IN ('table', 'querytable', 'query table')"
            ).fetchone()[0]
        )
        return result

    def write_summary(self, path: Any) -> None:
        counts = self.counts()
        workspace = self.connection.execute(
            "SELECT workspace_id, name FROM workspaces LIMIT 1"
        ).fetchone()
        type_rows = self.connection.execute(
            "SELECT view_type, COUNT(*) AS count FROM views GROUP BY view_type ORDER BY count DESC, view_type"
        ).fetchall()
        relationship_rows = self.connection.execute(
            "SELECT relationship_type, COUNT(*) AS count FROM relationships GROUP BY relationship_type ORDER BY count DESC, relationship_type"
        ).fetchall()
        table_rows = self.connection.execute(
            """
            SELECT v.view_id, v.name, v.view_type, COUNT(c.column_id) AS column_count
            FROM views v LEFT JOIN columns c ON c.view_id = v.view_id
            WHERE lower(v.view_type) IN ('table', 'querytable', 'query table')
            GROUP BY v.view_id, v.name, v.view_type ORDER BY v.name, v.view_id
            """
        ).fetchall()
        lines = [
            "# Zoho Analytics Workspace Metadata",
            "",
            "- Workspace: `%s` (%s)" % (
                workspace["name"] if workspace and workspace["name"] else "Unnamed",
                workspace["workspace_id"] if workspace else self.get_info("workspace_id", ""),
            ),
            "- Updated: %s" % self.get_info("updated_at", "unknown"),
            "- Views: %d" % counts["views"],
            "- Tables/query tables: %d" % counts["tables"],
            "- Columns: %d" % counts["columns"],
            "- Relationships: %d" % counts["relationships"],
            "- Errors: %d" % counts["errors"],
            "",
            "## View types",
            "",
            "| Type | Count |",
            "|---|---:|",
        ]
        lines.extend("| %s | %d |" % (row["view_type"] or "Unknown", row["count"]) for row in type_rows)
        lines.extend(["", "## Relationship types", "", "| Type | Count |", "|---|---:|"])
        lines.extend("| %s | %d |" % (row["relationship_type"], row["count"]) for row in relationship_rows)
        lines.extend(["", "## Tables", "", "| View | ID | Type | Columns |", "|---|---|---|---:|"])
        lines.extend(
            "| %s | `%s` | %s | %d |"
            % (row["name"].replace("|", "\\|"), row["view_id"], row["view_type"], row["column_count"])
            for row in table_rows
        )
        output = Path(path).expanduser().resolve()
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(output)

    def optimize(self) -> None:
        self.connection.execute("PRAGMA optimize")
        self.connection.execute("VACUUM")


__all__ = ["SCHEMA_VERSION", "WorkspaceMetadataStore"]
