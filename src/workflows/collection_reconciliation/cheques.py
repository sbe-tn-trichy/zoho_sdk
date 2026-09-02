"""Cheque presented-date lookup, normalization, and joining."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple
from zoho.helpers import normalize_cheque_number
from ..core.matching import to_text as _text



def attach_presented_dates(
    payments: Sequence[Dict[str, Any]],
    cheque_details: Sequence[Mapping[str, Any]],
) -> None:
    """Join presented dates from Creator All_Cheque_Details onto payment records."""
    details_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for detail in cheque_details:
        lookup = (
            detail.get("Payment_ID.Customer_Name")
            if isinstance(detail.get("Payment_ID.Customer_Name"), Mapping)
            else {}
        )
        key = (
            normalize_cheque_number(detail.get("Cheque_Number")),
            _text(lookup.get("ID")),
        )
        if all(key):
            details_by_key.setdefault(key, []).append(detail)

    for payment in payments:
        if _text(payment.get("_review_payment_type")).casefold() != "cheque":
            continue
        lookup = (
            payment.get("Customer_Name")
            if isinstance(payment.get("Customer_Name"), Mapping)
            else {}
        )
        key = (
            normalize_cheque_number(payment.get("Reference")),
            _text(lookup.get("ID")),
        )
        candidates = details_by_key.get(key, [])
        if len(candidates) != 1:
            payment["_review_presented_date"] = ""
            payment["_review_presented_date_error"] = (
                "No presented cheque detail matched cheque number and customer"
                if not candidates
                else "Multiple presented cheque details matched cheque number and customer"
            )
            continue

        presented_date = _text(candidates[0].get("Presented_Date"))
        payment["_review_presented_date"] = presented_date
        payment["_review_presented_date_error"] = (
            "The matched cheque detail has no Presented_Date"
            if not presented_date
            else ""
        )
        payment["_review_cheque_detail_id"] = _text(candidates[0].get("ID"))
