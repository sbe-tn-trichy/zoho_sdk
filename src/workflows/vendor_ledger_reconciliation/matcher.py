"""Public vendor-ledger reconciliation API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.models import DotDict
from ._reconciler import (
    check_bill_ref,
    check_credit_ref,
    check_payment_ref,
    fetch_vendor_credits,
    reconcile_document_group,
    reconcile_vendor as _reconcile_vendor,
    reconcile_vendor_account as _reconcile_vendor_account,
)


def reconcile_vendor_account(
    books_client: Any,
    vendor_id: str,
    vendor_ledger_path: str,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.01,
    skip_vendor_credits: bool = False,
) -> DotDict:
    """Full 4-way reconciliation (bills, payments, vendor credits, debit memos) against an external vendor ledger."""
    return DotDict(_reconcile_vendor_account(
        books_client=books_client,
        vendor_id=vendor_id,
        vendor_ledger_path=vendor_ledger_path,
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
        skip_vendor_credits=skip_vendor_credits,
    ))


def reconcile_vendor(
    vendor_ledger_path: str,
    vendor_id: Optional[str] = None,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
    books_client: Optional[Any] = None,
) -> DotDict:
    """High-level wrapper to reconcile a vendor account with client initialization and auto-detection."""
    return DotDict(_reconcile_vendor(
        vendor_ledger_path=vendor_ledger_path,
        vendor_id=vendor_id,
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
        books_client=books_client,
    ))


__all__ = [
    "fetch_vendor_credits",
    "check_credit_ref",
    "check_bill_ref",
    "check_payment_ref",
    "reconcile_document_group",
    "reconcile_vendor_account",
    "reconcile_vendor",
]
