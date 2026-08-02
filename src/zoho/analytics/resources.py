import csv
import io
import json
import time
from typing import Any, Dict, List, Optional

from .exceptions import ZohoAnalyticsError


_TABULAR_RESPONSE_FORMATS = {"csv", "json"}


def _response_format(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in _TABULAR_RESPONSE_FORMATS:
        supported = ", ".join(sorted(_TABULAR_RESPONSE_FORMATS))
        raise ValueError(
            f"Unsupported response_format {value!r}; structured row exports support: {supported}."
        )
    return normalized


def _rows(payload: Any, response_format: str = "csv") -> List[Dict[str, Any]]:
    response_format = _response_format(response_format)
    if isinstance(payload, bytes):
        text = payload.decode("utf-8-sig")
        if response_format == "csv":
            return list(csv.DictReader(io.StringIO(text)))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ZohoAnalyticsError("Analytics returned malformed JSON export data.") from exc
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    result_rows = result.get("data") if isinstance(result, dict) else None
    rows = payload.get("data") or payload.get("rows") or result_rows or []
    return rows if isinstance(rows, list) else []


class Views:
    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def _config(
        response_format: str,
        config: Optional[Dict[str, Any]] = None,
        **required: Any,
    ) -> Dict[str, str]:
        response_format = _response_format(response_format)
        export_config = dict(config or {})
        export_config.update(required)
        export_config["responseFormat"] = response_format
        return {"CONFIG": json.dumps(export_config)}

    def export_data(
        self,
        workspace_id: str,
        view_id: str,
        response_format: str = "csv",
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        payload = self.client.request(
            "GET",
            f"workspaces/{workspace_id}/views/{view_id}/data",
            params=self._config(response_format, config),
        )
        return _rows(payload, response_format)

    def export_all(
        self,
        workspace_id: str,
        view_id: str,
        poll_interval: float = 2.0,
        max_attempts: int = 12,
        response_format: str = "csv",
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            return self.export_data(
                workspace_id,
                view_id,
                response_format=response_format,
                config=config,
            )
        except ZohoAnalyticsError as exc:
            if "SYNC_EXPORT_NOT_ALLOWED" not in str(exc):
                raise
        return self.export_bulk(
            workspace_id,
            view_id,
            poll_interval=poll_interval,
            max_attempts=max_attempts,
            response_format=response_format,
            config=config,
        )

    def export_bulk(
        self,
        workspace_id: str,
        view_id: str,
        poll_interval: float = 2.0,
        max_attempts: int = 12,
        response_format: str = "csv",
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        base = f"bulk/workspaces/{workspace_id}"
        created = self.client.request(
            "GET",
            f"{base}/views/{view_id}/data",
            params=self._config(response_format, config),
        )
        return self._poll_export(
            workspace_id,
            created,
            poll_interval,
            max_attempts,
            response_format,
        )

    def query_data(
        self,
        workspace_id: str,
        sql_query: str,
        poll_interval: float = 2.0,
        max_attempts: int = 12,
        response_format: str = "csv",
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a dynamic SQL SELECT query through ZA's asynchronous export API."""
        if not sql_query or not sql_query.strip():
            raise ValueError("sql_query is required.")
        created = self.client.request(
            "GET",
            f"bulk/workspaces/{workspace_id}/data",
            params=self._config(response_format, config, sqlQuery=sql_query),
        )
        return self._poll_export(
            workspace_id,
            created,
            poll_interval,
            max_attempts,
            response_format,
        )

    def _poll_export(
        self,
        workspace_id: str,
        created: Any,
        poll_interval: float,
        max_attempts: int,
        response_format: str,
    ) -> List[Dict[str, Any]]:
        base = f"bulk/workspaces/{workspace_id}"
        job_id = created.get("data", {}).get("jobId") if isinstance(created, dict) else None
        if not job_id:
            raise ZohoAnalyticsError("Analytics bulk export did not return a job ID.")

        download_url = ""
        for attempt in range(max_attempts):
            status = self.client.request("GET", f"{base}/exportjobs/{job_id}")
            data = status.get("data", {}) if isinstance(status, dict) else {}
            if data.get("jobStatus") == "JOB COMPLETED":
                download_url = data.get("downloadUrl", "")
                break
            if data.get("jobStatus") in {"JOB FAILED", "JOB ABORTED"}:
                raise ZohoAnalyticsError(f"Analytics bulk export job {job_id} failed.")
            if attempt < max_attempts - 1:
                time.sleep(poll_interval)

        if not download_url:
            raise TimeoutError(f"Analytics bulk export job {job_id} did not complete.")
        return _rows(
            self.client.request("GET", "", override_url=download_url),
            response_format,
        )
