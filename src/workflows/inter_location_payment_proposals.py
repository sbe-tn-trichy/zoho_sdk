"""Review payment location moves using every allocated source document."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, TypedDict


class PaymentLocationProposal(TypedDict):
    payment_type: str
    payment_id: str
    date: str
    financial_year: str
    amount: str
    bank_account_id: str
    bank_account_name: str
    from_location_id: str
    from_location: str
    to_location_id: str
    to_location: str
    document_numbers: list[str]
    expected_number_prefix: str
    status: str
    reason: str


_OBSERVED_PAYMENT_PREFIXES = {
    "1094368000000443455": "SBE",
    "1094368000044509446": "SB",
    "1094368000000950615": "BL",
}


def expected_payment_prefix(location_id: str, financial_year: str, payment_type: str) -> str:
    """Observed location/FY/type prefix; exact series and next suffix need Books review."""
    location = _OBSERVED_PAYMENT_PREFIXES.get(location_id)
    year = {"FY 2025-26": "2526", "FY 2026-27": "2627"}.get(financial_year)
    kind = {"Customer Payment": "CP", "Vendor Payment": "VP"}.get(payment_type)
    return f"{location}{year}{kind}-" if location and year and kind else ""


def filter_payment_rows_for_year(
    rows: list[Mapping[str, Any]], financial_year: str,
) -> list[Mapping[str, Any]]:
    """Keep only QT payment rows belonging to the requested fiscal year."""
    if financial_year not in {"FY 2025-26", "FY 2026-27"}:
        raise ValueError(f"Unsupported financial year: {financial_year}")
    return [row for row in rows if str(row.get("Financial Year") or "") == financial_year]


def allocation_summary_query(payment_type: str) -> str:
    """Summarize all allocations, including rows absent from the mismatch QT."""
    if payment_type == "Customer Payment":
        payment_table, payment_alias, payment_id = "Customer Payments (Zoho Books)", "CP", "Payment ID"
        allocation_table, allocation_alias, document_table, document_alias, document_id = (
            "Invoice Payments (Zoho Books)", "IP", "Invoices (Zoho Books)", "I", "Invoice ID")
    elif payment_type == "Vendor Payment":
        payment_table, payment_alias, payment_id = "Vendor Payments (Zoho Books)", "VP", "Vendor Payment ID"
        allocation_table, allocation_alias, document_table, document_alias, document_id = (
            "Payments Made (Zoho Books)", "PM", "Bills (Zoho Books)", "B", "Bill ID")
    else:
        raise ValueError(f"Unsupported payment type: {payment_type}")
    return f'''SELECT {payment_alias}."{payment_id}" AS "Payment ID",
 MIN({document_alias}."Location ID") AS "Min Document Location ID",
 MAX({document_alias}."Location ID") AS "Max Document Location ID",
 COUNT({allocation_alias}."{document_id}") AS "Allocation Count",
 COUNT({document_alias}."{document_id}") AS "Found Count"
FROM "{payment_table}" {payment_alias}
JOIN "{allocation_table}" {allocation_alias}
 ON {payment_alias}."{payment_id}" = {allocation_alias}."{payment_id}"
LEFT JOIN "{document_table}" {document_alias}
 ON {allocation_alias}."{document_id}" = {document_alias}."{document_id}"
WHERE {payment_alias}."Payment Date" >= '2025-04-01'
 AND {payment_alias}."Payment Date" <= '2027-03-31'
GROUP BY {payment_alias}."{payment_id}"'''


def propose_payment_locations(
    rows: list[Mapping[str, Any]],
    allocation_summaries: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *,
    clearing_account_id: str = "1094368000002033114",
) -> list[PaymentLocationProposal]:
    """Propose only a uniform document location; hold conflicts and contra account rows."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        issue = str(row.get("Issue Type") or "")
        if issue not in {"Customer payment vs invoice", "Vendor payment vs bill"}:
            continue
        payment_type = str(row.get("Debit Type") or "")
        payment_id = str(row.get("Debit Transaction ID") or "")
        if payment_type not in {"Customer Payment", "Vendor Payment"} or not payment_id:
            raise ValueError("Mismatch row lacks a supported payment identity")
        grouped[(payment_type, payment_id)].append(row)
    proposals: list[PaymentLocationProposal] = []
    for (payment_type, payment_id), payment_rows in grouped.items():
        first = payment_rows[0]
        fixed = ("Date", "Financial Year", "Amount", "Bank Account ID", "Bank Account Name",
                 "Debit Location ID", "Debit Location")
        if any(any(str(row.get(key) or "") != str(first.get(key) or "") for key in fixed)
               for row in payment_rows[1:]):
            raise ValueError(f"Conflicting payment rows for {payment_id}")
        targets = {str(row.get("Credit Location ID") or "") for row in payment_rows}
        names = {str(row.get("Credit Location") or "") for row in payment_rows}
        source = str(first.get("Debit Location ID") or "")
        account = str(first.get("Bank Account ID") or "")
        summary = allocation_summaries.get(payment_type, {}).get(payment_id)
        target = next(iter(targets)) if len(targets) == 1 else ""
        if not source or not account or not target or not next(iter(names), ""):
            status, reason = "manual_review", "Missing or conflicting location information"
        elif target == source:
            raise ValueError(f"QT row is not inter-location: {payment_id}")
        elif not summary:
            status, reason = "manual_review", "Full allocation summary unavailable"
        elif (str(summary.get("Min Document Location ID") or "") != target or
              str(summary.get("Max Document Location ID") or "") != target or
              int(summary.get("Allocation Count") or 0) != int(summary.get("Found Count") or 0)):
            status, reason = "manual_review", "Allocated documents have multiple or missing locations"
        elif account == clearing_account_id:
            status, reason = "manual_review", "Clearing-account contra requires four-way review"
        else:
            status, reason = "proposed", "All allocated documents use the target location; verify current Books state before update"
        proposals.append({
            "payment_type": payment_type, "payment_id": payment_id,
            "date": str(first.get("Date") or ""), "financial_year": str(first.get("Financial Year") or ""),
            "amount": str(first.get("Amount") or ""), "bank_account_id": account,
            "bank_account_name": str(first.get("Bank Account Name") or ""),
            "from_location_id": source, "from_location": str(first.get("Debit Location") or ""),
            "to_location_id": target, "to_location": next(iter(names)) if len(names) == 1 else "",
            "document_numbers": sorted({str(row.get("Credit Reference") or "") for row in payment_rows
                                        if row.get("Credit Reference")}),
            "expected_number_prefix": expected_payment_prefix(
                target, str(first.get("Financial Year") or ""), payment_type),
            "status": status, "reason": reason,
        })
    return sorted(proposals, key=lambda p: (p["bank_account_name"], p["financial_year"], p["date"], p["payment_id"]))
