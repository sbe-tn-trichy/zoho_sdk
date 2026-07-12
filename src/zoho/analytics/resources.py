import csv
import io
import time
from typing import Any, Dict, List

from .exceptions import ZohoAnalyticsError


def _rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data") or payload.get("rows") or payload.get("result", {}).get("data") or []
    return rows if isinstance(rows, list) else []


class Views:
    def __init__(self, client: Any):
        self.client = client

    def export_data(self, workspace_id: str, view_id: str) -> List[Dict[str, Any]]:
        payload = self.client.request(
            "GET",
            f"workspaces/{workspace_id}/views/{view_id}/data",
        )
        return _rows(payload)

    def export_all(
        self,
        workspace_id: str,
        view_id: str,
        poll_interval: float = 2.0,
        max_attempts: int = 12,
    ) -> List[Dict[str, Any]]:
        try:
            return self.export_data(workspace_id, view_id)
        except ZohoAnalyticsError as exc:
            if "SYNC_EXPORT_NOT_ALLOWED" not in str(exc):
                raise
        return self.export_bulk(
            workspace_id,
            view_id,
            poll_interval=poll_interval,
            max_attempts=max_attempts,
        )

    def export_bulk(
        self,
        workspace_id: str,
        view_id: str,
        poll_interval: float = 2.0,
        max_attempts: int = 12,
    ) -> List[Dict[str, Any]]:
        base = f"bulk/workspaces/{workspace_id}"
        created = self.client.request("GET", f"{base}/views/{view_id}/data")
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
        return _rows(self.client.request("GET", "", override_url=download_url))
