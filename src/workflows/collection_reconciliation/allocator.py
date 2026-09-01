"""Oldest-due-first invoice balance allocation for customer payments."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.exceptions import ReconciliationError
from ..core.matching import to_decimal as _decimal, to_text as _text

CLOSED_INVOICE_STATUSES = {
    "void",
    "draft",
    "paid",
    "rejected",
    "pending_approval",
    "approval_overdue",
}


def fetch_open_invoices(books_client: Any, books_customer_id: str) -> List[Mapping[str, Any]]:
    """Fetch open, non-zero balance invoices for a customer from Zoho Books."""
    rows = books_client.invoices.list_all(params={"customer_id": books_customer_id})
    return [
        row
        for row in rows
        if isinstance(row, Mapping)
        and _text(row.get("status")).casefold() not in CLOSED_INVOICE_STATUSES
        and (_decimal(row.get("balance")) or Decimal("0")) > 0
        and _text(row.get("invoice_id"))
    ]


def allocate_invoices_oldest_due_first(
    payment_amount: Any,
    open_invoices: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """Allocate a payment amount across open invoices sorted by due date and invoice date."""
    amount = _decimal(payment_amount)
    if amount is None or amount == 0:
        raise ReconciliationError("A non-zero payment amount is required.")

    remaining = abs(amount)
    sorted_invoices = list(open_invoices)
    sorted_invoices.sort(
        key=lambda row: (
            _text(row.get("due_date")) or "9999-12-31",
            _text(row.get("date")) or "9999-12-31",
            _text(row.get("invoice_id")),
        )
    )

    allocations: List[Dict[str, Any]] = []
    for invoice in sorted_invoices:
        balance = _decimal(invoice.get("balance")) or Decimal("0")
        if balance <= 0 or remaining <= 0:
            continue
        applied = min(balance, remaining)
        allocations.append(
            {
                "invoice_id": _text(invoice.get("invoice_id")),
                "invoice_number": _text(invoice.get("invoice_number")),
                "date": _text(invoice.get("date")),
                "due_date": _text(invoice.get("due_date")),
                "balance": float(balance),
                "amount_applied": float(applied),
            }
        )
        remaining -= applied

    return allocations, remaining
