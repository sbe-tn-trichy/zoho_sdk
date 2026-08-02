"""Full 4-way vendor-account reconciliation (bills, payments, vendor credits,
debit memos) against an external vendor ledger file.

Public functions:
  - reconcile_vendor_account  — low-level, requires an initialised books_client
  - reconcile_vendor          — high-level wrapper with auto-detect and client init
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from ..core.matching import parse_date
from .cleaner import clean_ledger_file, get_ledger_metadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paginated fetch helpers
# ---------------------------------------------------------------------------

def fetch_vendor_credits(books_client: Any, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch all vendor credits through the SDK resource."""
    return books_client.vendor_credits.list_all(params=params, resource_key="vendor_credits")


# ---------------------------------------------------------------------------
# Document-type reference matchers
# ---------------------------------------------------------------------------

def check_credit_ref(vc: Dict[str, Any], l_cm: Dict[str, Any]) -> bool:
    vc_no  = str(vc.get("vendor_credit_number") or "").strip().lower()
    vc_ref = str(vc.get("reference_number") or "").strip().lower()
    led_no  = str(l_cm.get("transaction_no") or "").strip().lower()
    led_ref = str(l_cm.get("transaction_reference") or "").strip().lower()
    hits = []
    if led_no:
        hits.append(led_no == vc_no or led_no == vc_ref)
    if led_ref:
        hits.append(led_ref == vc_no or led_ref == vc_ref)
    return any(hits)


def check_bill_ref(b: Dict[str, Any], l_inv: Dict[str, Any]) -> bool:
    bill_no  = str(b.get("bill_number") or "").strip().lower()
    bill_ref = str(b.get("reference_number") or "").strip().lower()
    led_no   = str(l_inv.get("transaction_no") or "").strip().lower()
    led_ref  = str(l_inv.get("transaction_reference") or "").strip().lower()
    hits = []
    if led_no:
        hits.append(led_no == bill_no or led_no == bill_ref)
    if led_ref:
        hits.append(led_ref == bill_no or led_ref == bill_ref)
    return any(hits)


def check_payment_ref(p: Dict[str, Any], l_rec: Dict[str, Any]) -> bool:
    pay_ref = str(p.get("reference_number") or "").strip().lower()
    led_no  = str(l_rec.get("transaction_no") or "").strip().lower()
    led_ref = str(l_rec.get("transaction_reference") or "").strip().lower()
    hits = []
    if pay_ref:
        hits.append(pay_ref == led_no or pay_ref == led_ref)
    return any(hits)


# ---------------------------------------------------------------------------
# Generic 3-pass reconciliation engine
# ---------------------------------------------------------------------------

def reconcile_document_group(
    books_entries: List[Dict[str, Any]],
    ledger_entries: List[Dict[str, Any]],
    books_id_fn: Callable,
    books_date_fn: Callable,
    books_amount_fn: Callable,
    ledger_id_fn: Callable,
    ledger_date_fn: Callable,
    ledger_amount_fn: Callable,
    ref_match_fn: Callable,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
) -> Dict[str, Any]:
    """Generic 3-pass reconciliation algorithm for a single document type."""
    parsed_books = [
        {"id": books_id_fn(b), "date": books_date_fn(b), "amount": books_amount_fn(b), "raw": b}
        for b in books_entries
    ]
    parsed_ledger = [
        {"id": ledger_id_fn(l), "date": ledger_date_fn(l), "amount": ledger_amount_fn(l), "raw": l}
        for l in ledger_entries
    ]

    matched_books_ids: set = set()
    matched_ledger_ids: set = set()
    matches: list = []

    # Pass 1 — Exact: ref + amount + date
    for b in parsed_books:
        if not b["date"] or not b["id"]:
            continue
        for l in parsed_ledger:
            if l["id"] in matched_ledger_ids or not l["date"]:
                continue
            if not ref_match_fn(b["raw"], l["raw"]):
                continue
            if abs(b["amount"] - l["amount"]) > 1e-9:
                continue
            if abs((b["date"] - l["date"]).days) <= date_tolerance_days:
                matches.append((b["raw"], l["raw"]))
                matched_books_ids.add(b["id"])
                matched_ledger_ids.add(l["id"])
                break

    # Pass 2 — Strong: amount + date (no ref required)
    for b in parsed_books:
        if b["id"] in matched_books_ids or not b["date"]:
            continue
        for l in parsed_ledger:
            if l["id"] in matched_ledger_ids or not l["date"]:
                continue
            if abs(b["amount"] - l["amount"]) > 1e-9:
                continue
            if abs((b["date"] - l["date"]).days) <= date_tolerance_days:
                matches.append((b["raw"], l["raw"]))
                matched_books_ids.add(b["id"])
                matched_ledger_ids.add(l["id"])
                break

    # Pass 3 — Weak: amount within tolerance + date
    if amount_tolerance > 0.0:
        for b in parsed_books:
            if b["id"] in matched_books_ids or not b["date"]:
                continue
            for l in parsed_ledger:
                if l["id"] in matched_ledger_ids or not l["date"]:
                    continue
                if abs(b["amount"] - l["amount"]) > amount_tolerance:
                    continue
                if abs((b["date"] - l["date"]).days) <= date_tolerance_days:
                    matches.append((b["raw"], l["raw"]))
                    matched_books_ids.add(b["id"])
                    matched_ledger_ids.add(l["id"])
                    break

    return {
        "matches": matches,
        "unmatched_books": [b["raw"] for b in parsed_books if b["id"] not in matched_books_ids],
        "unmatched_ledger": [l["raw"] for l in parsed_ledger if l["id"] not in matched_ledger_ids],
    }


# ---------------------------------------------------------------------------
# High-level reconciliation functions
# ---------------------------------------------------------------------------

def reconcile_vendor_account(
    books_client: Any,
    vendor_id: str,
    vendor_ledger_path: str,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
) -> Dict[str, Any]:
    """
    Full 4-way reconciliation of a vendor account:
    Bills, Vendor Payments, Vendor Credits, and Debit Memos vs the ledger file.
    """
    metadata = get_ledger_metadata(vendor_ledger_path)
    start_date = parse_date(metadata.get("start_date"))
    end_date = parse_date(metadata.get("end_date"))

    ledger_entries = clean_ledger_file(vendor_ledger_path)
    if start_date and end_date:
        ledger_entries = [
            e for e in ledger_entries
            if e.get("date") and start_date <= parse_date(e["date"]) <= end_date
        ]

    def _ledger_by_type(doc_type: str) -> List[Dict[str, Any]]:
        return [
            e for e in ledger_entries
            if str(e.get("document_type") or "").strip().lower() == doc_type
        ]

    ledger_sales_invoices = _ledger_by_type("sales invoice")
    ledger_receipts       = _ledger_by_type("receipt")
    ledger_credit_memos   = _ledger_by_type("credit memo")
    ledger_debit_memos    = _ledger_by_type("debit memo")

    # --- fetch Zoho Books records ---
    date_params = {}
    if start_date and end_date:
        date_params = {
            "from_date": start_date.strftime("%Y-%m-%d"),
            "to_date": end_date.strftime("%Y-%m-%d"),
        }

    zoho_bills = books_client.bills.list_all(params={"vendor_id": vendor_id, **date_params})
    if start_date and end_date:
        zoho_bills = [
            b for b in zoho_bills
            if b.get("date") and start_date <= parse_date(b["date"]) <= end_date
        ]

    books_sales_invoices: List[Dict[str, Any]] = []
    books_debit_memos: List[Dict[str, Any]] = []
    for b in zoho_bills:
        try:
            total_val = float(b.get("total") or b.get("amount") or 0.0)
        except (ValueError, TypeError):
            total_val = 0.0
        if total_val < 0.0:
            books_debit_memos.append(b)
        else:
            books_sales_invoices.append(b)

    zoho_payments = books_client.vendor_payments.list_all(
        params={"vendor_id": vendor_id, **date_params}
    )
    if start_date and end_date:
        zoho_payments = [
            p for p in zoho_payments
            if p.get("date") and start_date <= parse_date(p["date"]) <= end_date
        ]

    zoho_vendor_credits = fetch_vendor_credits(
        books_client, {"vendor_id": vendor_id, **date_params}
    )
    if start_date and end_date:
        zoho_vendor_credits = [
            vc for vc in zoho_vendor_credits
            if vc.get("date") and start_date <= parse_date(vc["date"]) <= end_date
        ]

    # --- reconcile each document group ---
    common = dict(date_tolerance_days=date_tolerance_days, amount_tolerance=amount_tolerance)
    ledger_id_fn   = lambda l: l.get("id") or l.get("transaction_no")
    ledger_date_fn = lambda l: parse_date(l.get("date"))

    sales_invoice_results = reconcile_document_group(
        books_entries=books_sales_invoices,
        ledger_entries=ledger_sales_invoices,
        books_id_fn=lambda b: b.get("bill_id") or b.get("id"),
        books_date_fn=lambda b: parse_date(b.get("date")),
        books_amount_fn=lambda b: float(b.get("total") or b.get("amount") or 0.0),
        ledger_id_fn=ledger_id_fn,
        ledger_date_fn=ledger_date_fn,
        ledger_amount_fn=lambda l: float(l.get("debit_amount") or 0.0),
        ref_match_fn=check_bill_ref,
        **common,
    )

    receipt_results = reconcile_document_group(
        books_entries=zoho_payments,
        ledger_entries=ledger_receipts,
        books_id_fn=lambda p: p.get("payment_id") or p.get("id"),
        books_date_fn=lambda p: parse_date(p.get("date")),
        books_amount_fn=lambda p: float(p.get("amount") or 0.0),
        ledger_id_fn=ledger_id_fn,
        ledger_date_fn=ledger_date_fn,
        ledger_amount_fn=lambda l: float(l.get("credit_amount") or 0.0),
        ref_match_fn=check_payment_ref,
        **common,
    )

    credit_memo_results = reconcile_document_group(
        books_entries=zoho_vendor_credits,
        ledger_entries=ledger_credit_memos,
        books_id_fn=lambda vc: vc.get("vendor_credit_id") or vc.get("id"),
        books_date_fn=lambda vc: parse_date(vc.get("date")),
        books_amount_fn=lambda vc: float(vc.get("total") or vc.get("amount") or 0.0),
        ledger_id_fn=ledger_id_fn,
        ledger_date_fn=ledger_date_fn,
        ledger_amount_fn=lambda l: float(l.get("credit_amount") or 0.0),
        ref_match_fn=check_credit_ref,
        **common,
    )

    debit_memo_results = reconcile_document_group(
        books_entries=books_debit_memos,
        ledger_entries=ledger_debit_memos,
        books_id_fn=lambda b: b.get("bill_id") or b.get("id"),
        books_date_fn=lambda b: parse_date(b.get("date")),
        books_amount_fn=lambda b: abs(float(b.get("total") or b.get("amount") or 0.0)),
        ledger_id_fn=ledger_id_fn,
        ledger_date_fn=ledger_date_fn,
        ledger_amount_fn=lambda l: float(l.get("debit_amount") or 0.0),
        ref_match_fn=check_bill_ref,
        **common,
    )

    return {
        "sales_invoice": sales_invoice_results,
        "receipt":       receipt_results,
        "credit_memo":   credit_memo_results,
        "debit_memo":    debit_memo_results,
    }


def reconcile_vendor(
    vendor_ledger_path: str,
    vendor_id: Optional[str] = None,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
    books_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    High-level wrapper to reconcile a vendor account.
    - Initialises the Zoho Books client automatically if books_client is None.
    - Auto-detects the vendor ID from the ledger path (Polycab / Zeiss) if vendor_id is None.
    """
    from workflows.core.config import Config
    from workflows.core.auth import get_books_client

    if not books_client:
        books_client = get_books_client()

    if not vendor_id:
        filename = vendor_ledger_path.lower()
        if "277498" in filename or "polycab" in filename:
            vendor_id = Config.POLYCAB_VENDOR_ID
        elif "zeiss" in filename:
            vendor_id = Config.ZEISS_VENDOR_ID
        else:
            raise ValueError(
                f"Could not auto-detect vendor ID from ledger path: {vendor_ledger_path}. "
                "Please provide vendor_id explicitly."
            )

    return reconcile_vendor_account(
        books_client=books_client,
        vendor_id=vendor_id,
        vendor_ledger_path=vendor_ledger_path,
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
    )
