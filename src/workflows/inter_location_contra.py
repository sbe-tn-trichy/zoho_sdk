"""Review location mismatches between opposite postings in a Books account."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping


FY_RANGES = (("2025-04-01", "2026-03-31"), ("2026-04-01", "2027-03-31"))


@dataclass(frozen=True)
class AccountEntry:
    transaction_id: str
    transaction_type: str
    date: str
    location_id: str
    location_name: str
    direction: str
    amount: Decimal
    reference_number: str
    entry_number: str
    description: str

    def as_report(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def _value(record: Mapping[str, Any], *keys: str) -> str:
    return next((str(record[key]).strip() for key in keys if record.get(key) is not None and str(record[key]).strip()), "")


def _entry(record: Mapping[str, Any], transaction_type: str, detail: Mapping[str, Any] | None = None) -> AccountEntry:
    detail = detail or {}
    direction = _value(record, "debit_or_credit").lower()
    debit = Decimal(str(record.get("debit_amount") or 0))
    credit = Decimal(str(record.get("credit_amount") or 0))
    if direction not in {"debit", "credit"}:
        direction = "debit" if debit > 0 and credit == 0 else "credit" if credit > 0 and debit == 0 else ""
    amount = debit if direction == "debit" else credit
    if amount <= 0:
        amount = Decimal(str(record.get("amount") or 0))
    return AccountEntry(
        transaction_id=_value(record, "transaction_id"),
        transaction_type=_value(record, "transaction_type") or transaction_type,
        date=_value(record, "transaction_date", "date", "journal_date"),
        location_id=_value(detail, "location_id", "branch_id") or _value(record, "location_id", "branch_id"),
        location_name=_value(detail, "location_name", "branch_name") or _value(record, "location_name", "branch_name"),
        direction=direction,
        amount=amount,
        reference_number=_value(detail, "reference_number") or _value(record, "reference_number"),
        entry_number=_value(detail, "entry_number") or _value(record, "entry_number"),
        description=_value(detail, "description", "notes") or _value(record, "description", "notes"),
    )


def fetch_account_entries(books: Any, account_id: str, periods: tuple[tuple[str, str], ...] = FY_RANGES) -> list[AccountEntry]:
    """Fetch all pages of account-scoped bank transactions with posting details."""
    if not account_id:
        raise ValueError("account_id is required")
    entries: dict[tuple[str, str], AccountEntry] = {}
    for start, end in periods:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("Invalid date range")
        page = 1
        while True:
            response = books.bank_transactions.list({
                "account_id": account_id, "date_start": start, "date_end": end,
                "page": page, "per_page": 200,
            })
            if response.get("code", 0) != 0 or "banktransactions" not in response:
                raise ValueError(f"Books did not return account transactions for {start} to {end}")
            for raw in response["banktransactions"]:
                if _value(raw, "account_id") != account_id:
                    raise ValueError("Books returned a transaction from another account")
                entry = _entry(raw, _value(raw, "transaction_type"))
                if not entry.transaction_id or not entry.date or not entry.direction or entry.amount <= 0:
                    raise ValueError("Incomplete account transaction detail")
                if not start <= entry.date <= end:
                    raise ValueError("Books returned an out-of-period transaction")
                key = (entry.transaction_type, entry.transaction_id)
                if key in entries and entries[key] != entry:
                    raise ValueError(f"Conflicting duplicate transaction {key}")
                entries[key] = entry
            context = response.get("page_context") or {}
            if not context.get("has_more_page"):
                break
            page += 1
    return sorted(entries.values(), key=lambda entry: (entry.date, entry.transaction_type, entry.transaction_id))


def review_contras(entries: list[AccountEntry]) -> dict[str, Any]:
    """Pair unique opposite postings by date and amount; retain reference evidence."""
    groups: dict[tuple[str, Decimal], list[AccountEntry]] = defaultdict(list)
    for entry in entries:
        groups[(entry.date, entry.amount)].append(entry)
    candidates: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    same_location: list[dict[str, Any]] = []
    for (day, amount), rows in sorted(groups.items()):
        debits = [row for row in rows if row.direction == "debit"]
        credits = [row for row in rows if row.direction == "credit"]
        if not debits or not credits:
            continue
        if len(rows) != 2 or len(debits) != 1 or len(credits) != 1:
            ambiguous.append({"date": day, "amount": str(amount),
                              "transactions": [row.as_report() for row in rows]})
            continue
        debit, credit = debits[0], credits[0]
        left, right = debit.reference_number.strip().casefold(), credit.reference_number.strip().casefold()
        if left and right and left != right and left not in right and right not in left:
            ambiguous.append({"date": day, "amount": str(amount),
                              "reason": "unrelated references", "transactions": [row.as_report() for row in rows]})
            continue
        evidence = "exact_reference" if left and right and left == right else (
            "embedded_reference" if left and right else "date_amount_only")
        if not debit.location_id or not credit.location_id:
            ambiguous.append({"date": day, "amount": str(amount),
                              "reason": "missing location", "transactions": [row.as_report() for row in rows]})
            continue
        pair = {"date": day, "amount": str(amount), "matching_evidence": evidence,
                "debit": debit.as_report(), "credit": credit.as_report()}
        if debit.location_id == credit.location_id:
            same_location.append(pair)
            continue
        candidates.append({
            **pair, "reference": left or right,
            "review_status": "needs_review",
            "proposed_move": None,
            "review_instruction": "Choose the correct location and the specific source transaction after checking its underlying document.",
        })
    return {"transactions": [entry.as_report() for entry in entries],
            "inter_location_contras": candidates, "same_location_contras": same_location,
            "ambiguous": ambiguous}


def review_source_documents(books: Any, review: dict[str, Any]) -> dict[str, Any]:
    """Perform 4-way location check (bill, vendor payment, invoice, customer payment).
    
    All 4 locations must match for Vendor-Customer clearing offset transactions.
    """
    for pair in review["inter_location_contras"]:
        pair["proposed_move"] = None
        if pair["matching_evidence"] != "exact_reference":
            pair["review_instruction"] = "Verify this date/amount pair and source documents manually before any move."
            continue
        if pair["debit"]["transaction_type"] != "customer_payment" or pair["credit"]["transaction_type"] != "vendor_payment":
            continue
        customer = books.customer_payments.get(pair["debit"]["transaction_id"])["payment"]
        vendor = books.vendor_payments.get(pair["credit"]["transaction_id"])["vendorpayment"]
        if (str(customer.get("account_id")) != review["account_id"] or
                str(vendor.get("paid_through_account_id")) != review["account_id"] or
                str(customer.get("reference_number", "")).casefold() != pair["reference"] or
                str(vendor.get("reference_number", "")).casefold() != pair["reference"]):
            raise ValueError("Payment details changed since the account review")
        
        invoices = customer.get("invoices", [])
        bills = [books.bills.get(item["bill_id"])["bill"] for item in vendor.get("bills", [])]
        invoice_locations = Counter(str(item.get("location_id") or item.get("branch_id") or "") for item in invoices)
        bill_locations = Counter(str(item.get("location_id") or item.get("branch_id") or "") for item in bills)
        
        customer_pmt_loc = str(customer.get("location_id") or customer.get("branch_id") or "")
        vendor_pmt_loc = str(vendor.get("location_id") or vendor.get("branch_id") or "")
        
        all_locations = (set(invoice_locations) | set(bill_locations) | {customer_pmt_loc, vendor_pmt_loc}) - {""}
        is_4way_consistent = (
            len(all_locations) == 1
            and bool(customer_pmt_loc)
            and bool(vendor_pmt_loc)
            and bool(invoice_locations)
            and bool(bill_locations)
            and "" not in invoice_locations
            and "" not in bill_locations
        )

        pair["document_review"] = {
            "customer_payment_number": customer.get("payment_number"),
            "vendor_payment_number": vendor.get("payment_number"),
            "customer_payment_location": customer_pmt_loc,
            "vendor_payment_location": vendor_pmt_loc,
            "invoice_locations": dict(invoice_locations),
            "bill_locations": dict(bill_locations),
            "invoice_numbers": [item.get("invoice_number") for item in invoices],
            "bill_numbers": [item.get("bill_number") for item in bills],
            "four_way_location_consistent": is_4way_consistent,
            "distinct_locations": sorted(all_locations),
        }
        
        expected = set(invoice_locations) | set(bill_locations)
        if (invoices and bills and len(expected) == 1 and "" not in expected
                and next(iter(expected)) == pair["credit"]["location_id"]
                and customer_pmt_loc == pair["debit"]["location_id"]
                and vendor_pmt_loc == pair["credit"]["location_id"]):
            pair["proposed_move"] = {
                "transaction_type": "customer_payment",
                "transaction_id": customer["payment_id"],
                "from_location_id": customer["location_id"],
                "to_location_id": next(iter(expected)),
                "reason": "All allocated invoices and bills use the vendor payment location",
            }
        else:
            pair["review_instruction"] = (
                "Allocated documents or payments disagree on location; inspect all 4 locations "
                "(bill, vendor payment, invoice, customer payment) and resolve manually."
            )
    return review


def review_bank_payment_locations(
    books: Any,
    account_id: str,
    periods: tuple[tuple[str, str], ...] = FY_RANGES,
) -> dict[str, Any]:
    """Audit payment vs document location consistency for standard bank accounts.
    
    Rules:
    - For vendor payments (Payment Made): vendor_payment.location must match all allocated bill locations.
    - For customer payments (Payment Received): customer_payment.location must match all allocated invoice locations.
    """
    entries = fetch_account_entries(books, account_id, periods)
    mismatches: list[dict[str, Any]] = []
    audited_count = 0

    for entry in entries:
        if entry.transaction_type == "vendor_payment":
            audited_count += 1
            vendor = books.vendor_payments.get(entry.transaction_id)["vendorpayment"]
            pmt_loc = str(vendor.get("location_id") or vendor.get("branch_id") or "")
            bills = [books.bills.get(item["bill_id"])["bill"] for item in vendor.get("bills", [])]
            bill_locs = Counter(str(b.get("location_id") or b.get("branch_id") or "") for b in bills)
            
            # Mismatch if any bill has a location differing from payment location or missing location
            disagreeing = {loc for loc in bill_locs if loc != pmt_loc}
            if disagreeing or not pmt_loc or "" in bill_locs:
                mismatches.append({
                    "transaction_id": entry.transaction_id,
                    "transaction_type": "vendor_payment",
                    "payment_number": vendor.get("payment_number"),
                    "date": entry.date,
                    "amount": str(entry.amount),
                    "payment_location_id": pmt_loc,
                    "payment_location_name": entry.location_name,
                    "allocated_bill_numbers": [b.get("bill_number") for b in bills],
                    "allocated_bill_locations": dict(bill_locs),
                    "mismatch_reason": "Vendor payment location differs from allocated bill location(s)",
                })

        elif entry.transaction_type == "customer_payment":
            audited_count += 1
            customer = books.customer_payments.get(entry.transaction_id)["payment"]
            pmt_loc = str(customer.get("location_id") or customer.get("branch_id") or "")
            invoices = customer.get("invoices", [])
            inv_locs = Counter(str(inv.get("location_id") or inv.get("branch_id") or "") for inv in invoices)
            
            # Mismatch if any invoice has a location differing from payment location or missing location
            disagreeing = {loc for loc in inv_locs if loc != pmt_loc}
            if disagreeing or not pmt_loc or "" in inv_locs:
                mismatches.append({
                    "transaction_id": entry.transaction_id,
                    "transaction_type": "customer_payment",
                    "payment_number": customer.get("payment_number"),
                    "date": entry.date,
                    "amount": str(entry.amount),
                    "payment_location_id": pmt_loc,
                    "payment_location_name": entry.location_name,
                    "allocated_invoice_numbers": [inv.get("invoice_number") for inv in invoices],
                    "allocated_invoice_locations": dict(inv_locs),
                    "mismatch_reason": "Customer payment location differs from allocated invoice location(s)",
                })

    return {
        "account_id": account_id,
        "total_entries": len(entries),
        "audited_payments": audited_count,
        "mismatches": mismatches,
        "is_clean": len(mismatches) == 0,
    }


def add_analytics_location_evidence(review: dict[str, Any], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Attach exact payment/invoice matches from the Analytics mismatch view."""
    by_number: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        number = _value(row, "CP.Payment Number")
        if number:
            by_number[number].append(row)
    for pair in review["inter_location_contras"]:
        documents = pair.get("document_review") or {}
        number = documents.get("customer_payment_number")
        expected_invoices = set(documents.get("invoice_numbers") or [])
        matches = by_number.get(number, [])
        matched_invoices = {_value(row, "INV.Invoice Number") for row in matches}
        pair["analytics_evidence"] = {
            "view": "CustomerPaymentLocationDiff",
            "matched_rows": len(matches),
            "matched_invoice_numbers": sorted(matched_invoices),
            "all_allocated_invoices_present": bool(expected_invoices) and matched_invoices == expected_invoices,
            "locations": sorted({(_value(row, "Payment Recorded Location"),
                                  _value(row, "Invoice Location")) for row in matches}),
        }
    return review
