"""Review proposed payment location changes from an Analytics Query Table export."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, TypedDict


class LocationMove(TypedDict):
    transaction_type: str
    transaction_id: str
    from_location_id: str
    from_location: str
    to_location_id: str
    to_location: str


class LocationProposal(TypedDict):
    date: str
    financial_year: str
    amount: str
    customer_payment_id: str
    contra_type: str
    contra_id: str
    matching_evidence: str
    invoice_numbers: list[str]
    bill_numbers: list[str]
    invoice_locations: list[str]
    bill_locations: list[str]
    status: str
    reason: str
    moves: list[LocationMove]


def propose_location_updates(rows: list[Mapping[str, Any]]) -> list[LocationProposal]:
    """Group allocation rows; move payments only when their documents agree."""
    if not rows:
        raise ValueError("Query Table has no inter-location rows")
    rows = [row for row in rows if (row.get("Issue Type") or "Contra pair") == "Contra pair"]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("Debit Transaction ID") or not row.get("Credit Transaction ID"):
            raise ValueError("Query Table row lacks a source transaction ID")
        grouped[(str(row["Debit Transaction ID"]), str(row["Credit Transaction ID"]))].append(row)

    proposals: list[LocationProposal] = []
    fixed = ("Date", "Financial Year", "Amount", "Credit Type", "Matching Evidence",
             "Debit Location ID", "Credit Location ID")
    for (debit_id, credit_id), pair_rows in grouped.items():
        first = pair_rows[0]
        if any(any(str(row.get(key) or "") != str(first.get(key) or "") for key in fixed)
               for row in pair_rows[1:]):
            raise ValueError(f"Conflicting allocation rows for {debit_id}/{credit_id}")
        invoice_locs = {str(row.get("Invoice Location ID") or "") for row in pair_rows}
        bill_locs = {str(row.get("Bill Location ID") or "") for row in pair_rows}
        invoice_names = sorted({str(row.get("Invoice Location") or "") for row in pair_rows if row.get("Invoice Location")})
        bill_names = sorted({str(row.get("Bill Location") or "") for row in pair_rows if row.get("Bill Location")})
        invoice_numbers = sorted({str(row.get("Invoice Number") or "") for row in pair_rows if row.get("Invoice Number")})
        bill_numbers = sorted({str(row.get("Bill Number") or "") for row in pair_rows if row.get("Bill Number")})
        debit_loc = str(first.get("Debit Location ID") or "")
        credit_loc = str(first.get("Credit Location ID") or "")
        credit_type = str(first.get("Credit Type") or "")
        evidence = str(first.get("Matching Evidence") or "")
        moves: list[LocationMove] = []
        status = "manual_review"
        if not debit_loc or not credit_loc or debit_loc == credit_loc:
            raise ValueError(f"Pair {debit_id}/{credit_id} is not inter-location")
        if evidence != "Exact reference":
            reason = "Pairing needs source transaction verification"
        elif credit_type != "Vendor Payment":
            reason = "Journal contra needs source journal verification"
        elif not invoice_numbers or not bill_numbers or "" in invoice_locs or "" in bill_locs:
            reason = "Missing allocated invoice or bill location"
        elif len(invoice_locs | bill_locs) != 1:
            reason = "Allocated invoice and bill locations disagree"
        else:
            target = next(iter(invoice_locs))
            target_name = (invoice_names or bill_names or [target])[0]
            if debit_loc != target:
                moves.append({"transaction_type": "customer_payment", "transaction_id": debit_id,
                              "from_location_id": debit_loc, "from_location": str(first.get("Debit Location") or debit_loc),
                              "to_location_id": target, "to_location": target_name})
            if credit_loc != target:
                moves.append({"transaction_type": "vendor_payment", "transaction_id": credit_id,
                              "from_location_id": credit_loc, "from_location": str(first.get("Credit Location") or credit_loc),
                              "to_location_id": target, "to_location": target_name})
            status = "proposed"
            reason = "All allocated invoices and bills use the target location"
        proposals.append({"date": str(first.get("Date") or ""),
                          "financial_year": str(first.get("Financial Year") or ""),
                          "amount": str(first.get("Amount") or ""),
                          "customer_payment_id": debit_id, "contra_type": credit_type,
                          "contra_id": credit_id, "matching_evidence": evidence,
                          "invoice_numbers": invoice_numbers, "bill_numbers": bill_numbers,
                          "invoice_locations": invoice_names, "bill_locations": bill_names,
                          "status": status, "reason": reason, "moves": moves})
    return sorted(proposals, key=lambda item: (item["financial_year"], item["date"], item["customer_payment_id"]))
