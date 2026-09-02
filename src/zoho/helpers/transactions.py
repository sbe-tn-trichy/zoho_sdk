"""Higher-level helper functions for Zoho Books transaction lookups and response unwrapping."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("zoho.helpers.transactions")

CLOSED_DOCUMENT_STATUSES = {
    "void",
    "draft",
    "paid",
    "rejected",
    "pending_approval",
    "approval_overdue",
}


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def _to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_cheque_number(value: Any) -> str:
    """Normalize a cheque reference number by stripping non-alphanumerics and leading zeros."""
    normalized = "".join(
        character for character in _to_text(value).casefold() if character.isalnum()
    )
    return normalized.lstrip("0") or ("0" if normalized else "")


def fetch_open_invoices(
    books_client: Any,
    customer_id: str,
) -> List[Dict[str, Any]]:
    """Fetch open, non-zero balance invoices for a customer from Zoho Books."""
    customer_id_str = _to_text(customer_id)
    if not customer_id_str:
        return []
    rows = books_client.invoices.list_all(params={"customer_id": customer_id_str})
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and _to_text(row.get("status")).casefold() not in CLOSED_DOCUMENT_STATUSES
        and (_to_decimal(row.get("balance")) or Decimal("0")) > 0
        and _to_text(row.get("invoice_id"))
    ]


def fetch_open_bills(
    books_client: Any,
    vendor_id: str,
) -> List[Dict[str, Any]]:
    """Fetch open, non-zero balance bills for a vendor from Zoho Books."""
    vendor_id_str = _to_text(vendor_id)
    if not vendor_id_str:
        return []
    rows = books_client.bills.list_all(params={"vendor_id": vendor_id_str})
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and _to_text(row.get("status")).casefold() not in CLOSED_DOCUMENT_STATUSES
        and (_to_decimal(row.get("balance")) or Decimal("0")) > 0
        and _to_text(row.get("bill_id"))
    ]


def find_bill_by_number(
    books_client: Any,
    vendor_id: str,
    bill_number: str,
) -> Optional[Dict[str, Any]]:
    """Find a bill under a specific vendor by bill number."""
    vendor_id_str = _to_text(vendor_id)
    bill_no_str = _to_text(bill_number)
    if not vendor_id_str or not bill_no_str:
        return None

    try:
        res = books_client.bills.list(params={"vendor_id": vendor_id_str, "bill_number": bill_no_str})
        bills = res.get("bills", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
        for bill in bills:
            if _to_text(bill.get("bill_number")).casefold() == bill_no_str.casefold():
                return bill
        if bills:
            return bills[0]
    except Exception as exc:
        logger.warning(f"Error finding bill '{bill_no_str}' for vendor '{vendor_id_str}': {exc}")

    return None


def allocate_documents_fifo(
    amount: Any,
    documents: Sequence[Mapping[str, Any]],
    id_key: str = "invoice_id",
    include_metadata: bool = False,
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """Allocate a payment/credit amount across open documents sorted by due date and date.

    Returns a tuple of (allocations, unallocated_remaining_amount).
    """
    dec_amount = _to_decimal(amount)
    if dec_amount is None or dec_amount <= 0:
        raise ValueError("A positive amount is required for allocation.")

    remaining = dec_amount
    sorted_docs = list(documents)
    sorted_docs.sort(
        key=lambda row: (
            _to_text(row.get("due_date")) or "9999-12-31",
            _to_text(row.get("date")) or "9999-12-31",
            _to_text(row.get(id_key) or row.get("invoice_id") or row.get("bill_id")),
        )
    )

    allocations: List[Dict[str, Any]] = []
    for doc in sorted_docs:
        balance = _to_decimal(doc.get("balance")) or Decimal("0")
        doc_id = _to_text(doc.get(id_key) or doc.get("invoice_id") or doc.get("bill_id"))
        if not doc_id or balance <= 0 or remaining <= 0:
            continue
        applied = min(balance, remaining)
        allocation: Dict[str, Any] = {
            id_key: doc_id,
            "amount_applied": float(applied),
        }
        if include_metadata:
            if "invoice_number" in doc:
                allocation["invoice_number"] = _to_text(doc.get("invoice_number"))
            if "bill_number" in doc:
                allocation["bill_number"] = _to_text(doc.get("bill_number"))
            if "date" in doc:
                allocation["date"] = _to_text(doc.get("date"))
            if "due_date" in doc:
                allocation["due_date"] = _to_text(doc.get("due_date"))
            if "balance" in doc:
                allocation["balance"] = float(balance)

        allocations.append(allocation)
        remaining -= applied

    return allocations, remaining




def unwrap_record(
    response: Mapping[str, Any],
    candidate_keys: Sequence[str] = (),
) -> Dict[str, Any]:
    """Extract the primary record dictionary from a Zoho API response payload.

    Handles single-entity keys (e.g. 'salesorder', 'sales_order', 'payment', 'customerpayment',
    'invoice', 'creditnote', 'credit_note', 'bill', 'contact', 'item').
    """
    if not isinstance(response, Mapping):
        return {}

    # Check caller-provided candidate keys first
    for key in candidate_keys:
        val = response.get(key)
        if isinstance(val, dict):
            return val

    # Common Zoho Books single record entity keys
    common_keys = (
        "salesorder",
        "sales_order",
        "payment",
        "customerpayment",
        "customer_payment",
        "invoice",
        "creditnote",
        "credit_note",
        "bill",
        "vendorpayment",
        "vendor_payment",
        "contact",
        "customer",
        "vendor",
        "item",
        "bankaccount",
        "bank_account",
        "data",
    )
    for key in common_keys:
        val = response.get(key)
        if isinstance(val, dict):
            return val

    # Return copy of response dict if no wrapper key found
    return dict(response)


def find_transaction_by_number(
    resource: Any,
    number: str,
    number_keys: Sequence[str] = (
        "reference_number",
        "salesorder_number",
        "invoice_number",
        "payment_number",
        "creditnote_number",
        "bill_number",
    ),
    resource_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up a transaction in a Books resource (sales_orders, invoices, customer_payments, etc.) by reference or number."""
    target = str(number or "").strip()
    if not target:
        return None

    # Try querying via reference_number parameter
    try:
        if hasattr(resource, "list_all"):
            records = resource.list_all(params={"reference_number": target}, resource_key=resource_key)
        elif hasattr(resource, "list_iter"):
            records = list(resource.list_iter(params={"reference_number": target}, resource_key=resource_key))
        else:
            res = resource.list(params={"reference_number": target})
            records = res.get(resource_key or "data", []) if isinstance(res, dict) else []

        for record in records:
            for key in number_keys:
                if str(record.get(key) or "").strip() == target:
                    return record
    except Exception as exc:
        logger.warning(f"Error querying transaction by number '{target}': {exc}")

    return None
