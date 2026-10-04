"""Validated Analytics baselines with bounded live-resource change overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeVar

from .checkpoint import write_atomic_json

Baseline = TypeVar("Baseline")


class SnapshotResource(Protocol):
    def list(self, params: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SnapshotPolicy:
    """Resource/schema differences retained by the shared refresh engine."""

    id_key: str
    rows_key: str
    response_keys: tuple[str, ...]
    timestamp: Callable[[Any], datetime]
    label: str
    resource: str | None = None
    require_source_timezone: bool = False
    missing_page_is_empty: bool = False


def refresh_snapshot(
    *, api: SnapshotResource, snapshot_path: Path, organization_id: str,
    workspace_id: str, policy: SnapshotPolicy,
    analytics_loader: Callable[[], tuple[Baseline, datetime]],
    convert_baseline: Callable[[Baseline], Sequence[Mapping[str, Any]]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Reuse a scoped baseline, overlay validated 24h edits, then persist atomically.

    Adapters convert Analytics records and retain their own timestamp/empty-data
    policies. A failed load or incomplete live overlay never advances the snapshot.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = None
    if snapshot_path.is_file():
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if (loaded.get("schema_version") == 1
                and loaded.get("organization_id") == organization_id
                and loaded.get("workspace_id") == workspace_id
                and (policy.resource is None or loaded.get("resource") == policy.resource)):
            previous = loaded
    if previous and current - policy.timestamp(previous["checked_at"]) <= timedelta(hours=24):
        baseline = previous[policy.rows_key]
        source_at = policy.timestamp(previous["analytics_at"])
    else:
        raw_baseline, source_at = analytics_loader()
        if policy.require_source_timezone and source_at.tzinfo is None:
            raise ValueError("Analytics export timestamp must include a timezone")
        source_at = source_at.astimezone(timezone.utc)
        if current - source_at > timedelta(hours=24):
            raise ValueError(f"Analytics {policy.label} baseline is older than 24 hours")
        baseline = convert_baseline(raw_baseline)

    by_id = {str(row[policy.id_key]): dict(row) for row in baseline}
    cutoff = current - timedelta(hours=24)
    parameter = cutoff.strftime("%Y-%m-%dT%H:%M:%S+0000")
    page = 1
    while True:
        response = api.list(params={"last_modified_time": parameter, "page": page, "per_page": 200})
        rows = [] if policy.missing_page_is_empty else None
        for key in policy.response_keys:
            if key in response:
                rows = response[key]
                break
        if not isinstance(rows, list):
            raise ValueError(f"Books returned an invalid {policy.response_keys[0]} page")
        for row in rows:
            row_id = str(row.get(policy.id_key) or "")
            modified = row.get("last_modified_time")
            if not row_id or not modified:
                raise ValueError(f"Books changed {policy.label} row lacks ID or modified time")
            if policy.timestamp(modified) < cutoff - timedelta(minutes=5):
                raise ValueError(f"Books did not honor the {policy.label} last_modified_time filter")
            by_id[row_id] = dict(row)
        if not response.get("page_context", {}).get("has_more_page", False):
            break
        if not rows:
            raise ValueError(f"Books reported more changed {policy.label} pages but returned no rows")
        page += 1

    result = list(by_id.values())
    payload = {
        "schema_version": 1, "organization_id": organization_id,
        "workspace_id": workspace_id, "analytics_at": source_at.isoformat(),
        "checked_at": current.isoformat(), policy.rows_key: result,
    }
    if policy.resource is not None:
        payload["resource"] = policy.resource
    write_atomic_json(snapshot_path, payload, indent=None, ensure_ascii=False, default=None)
    return result
