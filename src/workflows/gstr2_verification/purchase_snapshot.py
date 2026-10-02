"""Analytics baselines with validated recent Books changes for purchase resources."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from zoho.helpers import parse_date

from .bill_snapshot import _money


def _date(value: Any) -> str:
    parsed = parse_date(value)
    if parsed is None:
        raise ValueError(f"Invalid Analytics purchase date: {value!r}")
    return parsed.isoformat()


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return parsed.astimezone(timezone.utc)


def convert_analytics_expenses(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map Analytics Expenses rows to fields consumed by the verifier."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        expense_id = str(row.get("Expense ID") or "").strip()
        if not expense_id or not row.get("Last Modified Time") or "Tax Value" not in row:
            raise ValueError("Analytics expense lacks ID, modified time, or tax value")
        if expense_id in result:
            raise ValueError(f"Duplicate Analytics expense ID: {expense_id}")
        result[expense_id] = {
            "expense_id": expense_id,
            "date": _date(row.get("Expense Date")),
            "reference_number": str(row.get("Reference Number") or ""),
            "vendor_id": str(row.get("Vendor ID") or ""),
            "vendor_name": str(row.get("Merchant Name") or ""),
            "gst_no": str(row.get("GSTIN") or ""),
            "location_id": str(row.get("Location ID") or ""),
            "status": str(row.get("Status") or "").lower(),
            "total": _money(row.get("Total (BCY)")),
            "sub_total": _money(row.get("Sub Total (BCY)")),
            "tax_amount": _money(row["Tax Value"]),
            "last_modified_time": _timestamp(row["Last Modified Time"]).isoformat(),
        }
    return list(result.values())


def convert_analytics_credits(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map Analytics Vendor Credits rows to fields consumed by the verifier."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        credit_id = str(row.get("Vendor Credit ID") or "").strip()
        if not credit_id or not row.get("Last Modified Time") or "GST Present" not in row:
            raise ValueError("Analytics vendor credit lacks ID, modified time, or GST value")
        if credit_id in result:
            raise ValueError(f"Duplicate Analytics vendor credit ID: {credit_id}")
        result[credit_id] = {
            "vendor_credit_id": credit_id,
            "vendor_credit_number": str(row.get("Vendor Credit Number") or ""),
            "reference_number": str(row.get("Reference Number") or ""),
            "date": _date(row.get("Vendor Credit Date")),
            "vendor_id": str(row.get("Vendor ID") or ""),
            "vendor_name": str(row.get("Vendor Name") or ""),
            "gst_no": str(row.get("GSTIN") or ""),
            "location_id": str(row.get("Location ID") or ""),
            "status": str(row.get("Vendor Credit Status") or "").lower(),
            "total": _money(row.get("Total (BCY)")),
            "balance": _money(row.get("Balance (BCY)")),
            "sub_total": _money(row.get("Sub Total (BCY)")),
            "tax_total": _money(row["GST Present"]),
            "last_modified_time": _timestamp(row["Last Modified Time"]).isoformat(),
        }
    return list(result.values())


def refresh_purchase_snapshot(
    *, books: Any, resource: str, snapshot_path: Path,
    organization_id: str, workspace_id: str,
    analytics_loader: Callable[[], tuple[Sequence[Mapping[str, Any]], datetime]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Overlay only recent Books rows; reject ignored filters or incomplete pages."""
    if resource not in {"expenses", "vendor_credits"}:
        raise ValueError(f"Unsupported purchase resource: {resource}")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    id_key = "expense_id" if resource == "expenses" else "vendor_credit_id"
    response_key = "expenses" if resource == "expenses" else "vendor_credits"
    previous = None
    if snapshot_path.is_file():
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if (loaded.get("schema_version") == 1 and loaded.get("resource") == resource
                and loaded.get("organization_id") == organization_id
                and loaded.get("workspace_id") == workspace_id):
            previous = loaded
    if previous and current - _timestamp(previous["checked_at"]) <= timedelta(hours=24):
        baseline = previous["rows"]
        source_at = _timestamp(previous["analytics_at"])
    else:
        rows, source_at = analytics_loader()
        source_at = source_at.astimezone(timezone.utc)
        if current - source_at > timedelta(hours=24):
            raise ValueError(f"Analytics {resource} baseline is older than 24 hours")
        baseline = (convert_analytics_expenses(rows) if resource == "expenses"
                    else convert_analytics_credits(rows))
    by_id = {str(row[id_key]): dict(row) for row in baseline}
    cutoff = current - timedelta(hours=24)
    parameter = cutoff.strftime("%Y-%m-%dT%H:%M:%S+0000")
    api = getattr(books, resource)
    page = 1
    while True:
        response = api.list(params={"last_modified_time": parameter, "page": page, "per_page": 200})
        rows = response.get(response_key, response.get("vendorcredits") if resource == "vendor_credits" else None)
        if not isinstance(rows, list):
            raise ValueError(f"Books returned an invalid {resource} page")
        for row in rows:
            row_id = str(row.get(id_key) or "")
            modified = row.get("last_modified_time")
            if not row_id or not modified:
                raise ValueError(f"Books changed {resource} row lacks ID or modified time")
            if _timestamp(modified) < cutoff - timedelta(minutes=5):
                raise ValueError(f"Books did not honor the {resource} last_modified_time filter")
            by_id[row_id] = dict(row)
        if not response.get("page_context", {}).get("has_more_page", False):
            break
        if not rows:
            raise ValueError(f"Books reported more {resource} pages but returned no rows")
        page += 1
    payload = {"schema_version": 1, "resource": resource,
               "organization_id": organization_id, "workspace_id": workspace_id,
               "analytics_at": source_at.isoformat(), "checked_at": current.isoformat(),
               "rows": list(by_id.values())}
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(snapshot_path)
    return payload["rows"]
