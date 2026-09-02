"""Oldest-due-first invoice balance allocation for customer payments."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from zoho.helpers import (
    CLOSED_DOCUMENT_STATUSES as CLOSED_INVOICE_STATUSES,
    allocate_documents_fifo,
    fetch_open_invoices,
)
from ..core.exceptions import ReconciliationError
from ..core.matching import to_decimal as _decimal, to_text as _text


def allocate_invoices_oldest_due_first(
    payment_amount: Any,
    open_invoices: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """Allocate a payment amount across open invoices sorted by due date and invoice date."""
    amount = _decimal(payment_amount)
    if amount is None or amount == 0:
        raise ReconciliationError("A non-zero payment amount is required.")

    return allocate_documents_fifo(
        abs(amount),
        open_invoices,
        id_key="invoice_id",
        include_metadata=True,
    )


