"""Analytics-backed bill snapshot with a bounded Books change overlay."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from zoho.helpers import parse_date


def _money(value: Any) -> float:
    cleaned = re.sub(r"[^\d.\-]", "", str(value or ""))
    return float(cleaned) if cleaned not in {"", "-", "."} else 0.0


def _iso_date(value: Any) -> str:
    parsed = parse_date(value)
    if parsed is None:
        raise ValueError(f"Invalid Analytics bill date: {value!r}")
    return parsed.isoformat()


def convert_analytics_bills(
    bill_rows: Sequence[Mapping[str, Any]],
    vendor_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map complete Analytics bill exports into the Books list shape."""
    vendors = {str(row.get("Vendor ID") or ""): row for row in vendor_rows}
    bills: dict[str, dict[str, Any]] = {}
    for row in bill_rows:
        bill_id = str(row.get("Bill ID") or "").strip()
        vendor_id = str(row.get("Vendor ID") or "").strip()
        if not bill_id or not vendor_id or not row.get("Last Modified Time"):
            raise ValueError("Analytics bill export lacks ID, vendor ID, or modified time")
        if bill_id in bills:
            raise ValueError(f"Duplicate Analytics bill ID: {bill_id}")
        vendor = vendors.get(vendor_id, {})
        tax_total = sum(_money(row.get(f"{component} Amount"))
                        for component in ("CGST", "SGST", "IGST", "CESS"))
        bills[bill_id] = {
            "bill_id": bill_id,
            "vendor_id": vendor_id,
            "vendor_name": str(vendor.get("Vendor Name") or ""),
            "bill_number": str(row.get("Bill Number") or ""),
            "reference_number": str(row.get("Reference Number") or ""),
            "date": _iso_date(row.get("Bill Date")),
            "txn_value_date": _iso_date(row.get("Transaction Posting Date") or row.get("Bill Date")),
            "location_id": str(row.get("Location ID") or ""),
            "gst_no": str(row.get("GSTIN") or vendor.get("GSTIN") or ""),
            "status": str(row.get("Bill Status") or "").lower(),
            "total": _money(row.get("Total (BCY)")),
            "balance": _money(row.get("Balance (BCY)")),
            "sub_total": _money(row.get("Sub Total (BCY)")),
            "tax_total": tax_total,
            "last_modified_time": str(row["Last Modified Time"]),
        }
    if not bills:
        raise ValueError("Analytics bill export is empty")
    return list(bills.values())


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def unchanged_zero_tax_expenses(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, datetime]:
    """Index zero-tax Analytics expenses by their Books modification instant."""
    result: dict[str, datetime] = {}
    for row in rows:
        expense_id = str(row.get("Expense ID") or "")
        modified = str(row.get("Last Modified Time") or "")
        if not expense_id or not modified or _money(row.get("Tax Value")) != 0:
            continue
        parsed = datetime.fromisoformat(modified)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        result[expense_id] = parsed.astimezone(timezone.utc)
    return result


def refresh_bill_snapshot(
    *,
    books: Any,
    snapshot_path: Path,
    organization_id: str,
    workspace_id: str,
    analytics_loader: Callable[[], tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]], datetime]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Use a recent local snapshot or Analytics, then overlay 24h Books edits.

    A stale snapshot is rebased from Analytics before the delta. Snapshot writes
    occur only after all pages pass validation, preserving the prior good copy.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot: Mapping[str, Any] | None = None
    if snapshot_path.is_file():
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if (loaded.get("schema_version") == 1
                and loaded.get("organization_id") == organization_id
                and loaded.get("workspace_id") == workspace_id):
            snapshot = loaded
    if snapshot and current - _timestamp(str(snapshot["checked_at"])) <= timedelta(hours=24):
        baseline = list(snapshot["bills"])
        source_at = _timestamp(str(snapshot["analytics_at"]))
    else:
        bill_rows, vendor_rows, source_at = analytics_loader()
        if source_at.tzinfo is None:
            raise ValueError("Analytics export timestamp must include a timezone")
        source_at = source_at.astimezone(timezone.utc)
        if current - source_at > timedelta(hours=24):
            raise ValueError("Analytics bill baseline is older than 24 hours")
        baseline = convert_analytics_bills(bill_rows, vendor_rows)

    # The 24-hour overlap covers Analytics' three-hour sync lag and edits made
    # while the export was running. Do not advance the snapshot on API failure.
    cutoff = current - timedelta(hours=24)
    parameter = cutoff.strftime("%Y-%m-%dT%H:%M:%S+0000")
    by_id = {str(row["bill_id"]): dict(row) for row in baseline}
    page = 1
    while True:
        response = books.bills.list(params={
            "last_modified_time": parameter, "page": page, "per_page": 200,
        })
        rows = response.get("bills", [])
        if not isinstance(rows, list):
            raise ValueError("Books returned an invalid bills page")
        for row in rows:
            bill_id = str(row.get("bill_id") or "")
            modified = str(row.get("last_modified_time") or "")
            if not bill_id or not modified:
                raise ValueError("Books changed bill lacks ID or modified time")
            parsed = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.astimezone(timezone.utc) < cutoff - timedelta(minutes=5):
                raise ValueError("Books did not honor the last_modified_time filter")
            by_id[bill_id] = dict(row)
        if not response.get("page_context", {}).get("has_more_page", False):
            break
        if not rows:
            raise ValueError("Books reported more changed bills but returned an empty page")
        page += 1

    payload = {
        "schema_version": 1,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "analytics_at": source_at.isoformat(),
        "checked_at": current.isoformat(),
        "bills": list(by_id.values()),
    }
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(snapshot_path)
    return payload["bills"]
