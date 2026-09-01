"""Higher-level helper functions for Zoho Books transaction lookups and response unwrapping."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Sequence

logger = logging.getLogger("zoho.helpers.transactions")


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
