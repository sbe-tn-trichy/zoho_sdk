"""Build read-only split proposals from current Books payment allocations."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Mapping

from workflows.inter_location_payment_proposals import expected_payment_prefix


def money(value: Any) -> Decimal:
    return Decimal(str(value).replace("INR", "").replace(",", "").strip()).quantize(Decimal("0.01"))


def propose_split(
    proposal: Mapping[str, Any], payment: Mapping[str, Any],
    documents: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group verified allocations by document location without changing Books."""
    payment_id = str(proposal["payment_id"])
    kind = str(proposal["payment_type"])
    allocations = payment.get("invoices" if kind == "Customer Payment" else "bills") or []
    document_id_key = "invoice_id" if kind == "Customer Payment" else "bill_id"
    if str(payment.get("payment_id")) != payment_id:
        raise ValueError(f"Payment identity differs: {payment_id}")
    if len(documents) != len(allocations) or not allocations:
        raise ValueError(f"Document count differs: {payment_id}")
    by_id = {str(d[document_id_key]): d for d in documents}
    if len(by_id) != len(documents):
        raise ValueError(f"Duplicate allocated document: {payment_id}")
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"amount": Decimal("0"), "documents": []})
    missing = False
    for allocation in allocations:
        document_id = str(allocation[document_id_key])
        document = by_id.get(document_id)
        if document is None:
            raise ValueError(f"Allocated document missing: {payment_id}/{document_id}")
        amount = money(allocation["amount_applied"])
        if amount <= 0:
            raise ValueError(f"Nonpositive allocation: {payment_id}/{document_id}")
        location_id = str(document.get("location_id") or "")
        if not location_id:
            missing = True
        group = groups[location_id]
        group["amount"] += amount
        group["location"] = str(document.get("location_name") or location_id)
        group["documents"].append({
            "id": document_id,
            "number": str(document.get("invoice_number" if kind == "Customer Payment" else "bill_number") or ""),
            "amount": str(amount),
        })
    total = money(payment["amount"])
    allocated = sum((g["amount"] for g in groups.values()), Decimal("0"))
    unused = money(payment.get("unused_amount") or 0)
    source = str(payment.get("location_id") or "")
    result: dict[str, Any] = {
        "payment_type": kind, "payment_id": payment_id,
        "payment_number": str(payment.get("payment_number") or ""),
        "date": str(payment.get("date") or ""), "amount": str(total),
        "current_location_id": source,
        "current_location": str(payment.get("location_name") or source),
        "allocated_amount": str(allocated), "unused_amount": str(unused),
        "status": "manual_review", "reason": "", "retain": None, "create": [],
    }
    if missing or not source or total != allocated or unused != 0:
        result["reason"] = "Missing location or payment amount is not fully allocated"
    elif len(groups) == 1:
        result["reason"] = "All allocations use one location; review a location move, not a split"
    elif source not in groups:
        result["reason"] = "No allocation belongs to the payment's current location"
    else:
        result["status"] = "split_proposed"
        result["reason"] = "Keep the source-location portion; create one payment per other location"
        result["retain"] = _part(source, groups[source], kind, str(proposal["financial_year"]))
        result["create"] = [
            _part(location_id, group, kind, str(proposal["financial_year"]))
            for location_id, group in sorted(groups.items()) if location_id != source
        ]
    return result


def _part(location_id: str, group: Mapping[str, Any], kind: str, year: str) -> dict[str, Any]:
    return {"location_id": location_id, "location": group["location"],
            "amount": str(group["amount"]), "documents": group["documents"],
            "observed_number_prefix": expected_payment_prefix(location_id, year, kind)}
