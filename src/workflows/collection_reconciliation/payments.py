"""Shared Books customer-payment payload fields for Creator collections."""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence

from ..core.exceptions import ReconciliationError


def customer_payment_payload(
    *,
    customer_id: str,
    payment_mode: str,
    payment_date: Optional[date],
    amount: Optional[Decimal],
    reference_number: str,
    description: str,
    account_id: str,
    creator_record_id: str,
    creator_payment_id: Any = None,
    invoices: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    if not payment_date or amount is None:
        raise ReconciliationError("A valid payment date and amount are required.")
    custom_fields = [{"label": "Creator Record ID", "value": creator_record_id}]
    if creator_payment_id not in (None, ""):
        custom_fields.append({"label": "Creator Payment ID", "value": creator_payment_id})
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "payment_mode": payment_mode,
        "date": payment_date.isoformat(),
        "amount": float(abs(amount)),
        "reference_number": reference_number,
        "description": description,
        "account_id": account_id,
        "custom_fields": custom_fields,
    }
    if invoices is not None:
        payload["invoices"] = [
            {"invoice_id": row["invoice_id"], "amount_applied": row["amount_applied"]}
            for row in invoices
        ]
    return payload
