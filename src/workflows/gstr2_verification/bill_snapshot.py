"""Analytics-backed bill snapshot with a bounded Books change overlay."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from zoho.helpers import parse_date

from workflows.core.snapshots import SnapshotPolicy, refresh_snapshot


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
    *, books: Any, snapshot_path: Path, organization_id: str, workspace_id: str,
    analytics_loader: Callable[[], tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]], datetime]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Refresh the bill schema using a validated Analytics/Books overlay."""
    def load_baseline() -> tuple[tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]], datetime]:
        bills, vendors, source_at = analytics_loader()
        return (bills, vendors), source_at

    return refresh_snapshot(
        api=books.bills, snapshot_path=snapshot_path, organization_id=organization_id,
        workspace_id=workspace_id, analytics_loader=load_baseline, now=now,
        convert_baseline=lambda rows: convert_analytics_bills(*rows),
        policy=SnapshotPolicy(id_key="bill_id", rows_key="bills", response_keys=("bills",),
                              timestamp=_timestamp, label="bill", require_source_timezone=True,
                              missing_page_is_empty=True),
    )
