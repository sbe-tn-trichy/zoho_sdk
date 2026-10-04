"""Analytics baselines with validated recent Books changes for purchase resources."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from zoho.helpers import parse_date

from .bill_snapshot import _money

from workflows.core.snapshots import SnapshotPolicy, refresh_snapshot


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
    """Refresh expense/credit schemas with validated recent Books changes."""
    if resource not in {"expenses", "vendor_credits"}:
        raise ValueError(f"Unsupported purchase resource: {resource}")

    return refresh_snapshot(
        api=getattr(books, resource), snapshot_path=snapshot_path,
        organization_id=organization_id, workspace_id=workspace_id,
        analytics_loader=analytics_loader, now=now,
        convert_baseline=convert_analytics_expenses if resource == "expenses" else convert_analytics_credits,
        policy=SnapshotPolicy(
            id_key="expense_id" if resource == "expenses" else "vendor_credit_id",
            rows_key="rows", response_keys=("expenses",) if resource == "expenses"
                else ("vendor_credits", "vendorcredits"),
            timestamp=_timestamp, label=resource, resource=resource,
        ),
    )
