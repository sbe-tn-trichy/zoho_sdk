"""Matches Zoho Books bank-account withdrawals against either:
  - Zoho Books vendor payments (match_ledger_entries)
  - An external vendor ledger file on disk (match_bank_with_vendor_ledger)
"""
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional
from datetime import date

from ..core.matching import get_bank_reference, parse_date, get_abs_amount, ref_match
from ..vendor_ledger_reconciliation.cleaner import clean_ledger_file, get_ledger_metadata

logger = logging.getLogger(__name__)


def _extract_withdrawals(bank_txs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter a list of bank transactions down to outflows (withdrawals / debits)."""
    withdrawals = []
    for tx in bank_txs:
        amount_val = 0.0
        try:
            amount_val = float(tx.get("amount", 0.0))
        except (ValueError, TypeError):
            pass

        is_withdrawal = (
            amount_val < 0
            or str(tx.get("debit_or_credit")).lower() == "debit"
            or str(tx.get("transaction_type")).lower() in ("expense", "withdrawal", "payment")
            or str(tx.get("type")).lower() in ("expense", "withdrawal", "payment")
        )
        if is_withdrawal:
            withdrawals.append(tx)
    return withdrawals


def _run_three_pass_match(
    parsed_left: List[Dict[str, Any]],
    left_id_key: str,
    parsed_right: List[Dict[str, Any]],
    right_id_key: str,
    date_tolerance_days: int,
    amount_tolerance: float,
) -> tuple:
    """
    Generic 3-pass match between two pre-parsed lists.
    Each item must have: id, date, amount, ref, raw.
    Returns (exact_matches, strong_matches, weak_matches, matched_left_ids, matched_right_ids).
    """
    matched_left_ids: set = set()
    matched_right_ids: set = set()
    exact_matches: list = []
    strong_matches: list = []
    weak_matches: list = []

    # Pass 1 — Exact: ref + amount + date
    for l in parsed_left:
        if not l["date"] or not l["id"]:
            continue
        for r in parsed_right:
            if r["id"] in matched_right_ids or not r["date"]:
                continue
            if not ref_match(l["ref"], r["ref"]):
                continue
            if abs(l["amount"] - r["amount"]) > 1e-9:
                continue
            if abs((l["date"] - r["date"]).days) <= date_tolerance_days:
                exact_matches.append((l["raw"], r["raw"]))
                matched_left_ids.add(l["id"])
                matched_right_ids.add(r["id"])
                break

    # Pass 2 — Strong: amount + date (no ref required)
    for l in parsed_left:
        if l["id"] in matched_left_ids or not l["date"]:
            continue
        for r in parsed_right:
            if r["id"] in matched_right_ids or not r["date"]:
                continue
            if abs(l["amount"] - r["amount"]) > 1e-9:
                continue
            if abs((l["date"] - r["date"]).days) <= date_tolerance_days:
                strong_matches.append((l["raw"], r["raw"]))
                matched_left_ids.add(l["id"])
                matched_right_ids.add(r["id"])
                break

    # Pass 3 — Weak: amount within tolerance + date
    if amount_tolerance > 0.0:
        for l in parsed_left:
            if l["id"] in matched_left_ids or not l["date"]:
                continue
            for r in parsed_right:
                if r["id"] in matched_right_ids or not r["date"]:
                    continue
                if abs(l["amount"] - r["amount"]) > amount_tolerance:
                    continue
                if abs((l["date"] - r["date"]).days) <= date_tolerance_days:
                    weak_matches.append((l["raw"], r["raw"]))
                    matched_left_ids.add(l["id"])
                    matched_right_ids.add(r["id"])
                    break

    return exact_matches, strong_matches, weak_matches, matched_left_ids, matched_right_ids


def match_ledger_entries(
    books_client: Any,
    bank_account_id: str,
    vendor_id: str,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Matches Bank Account withdrawals with Vendor Payments in Zoho Books.
    Both sides are fetched live from the API.
    """
    params: Dict[str, Any] = {"account_id": bank_account_id}
    if start_date and end_date:
        search_start = start_date - timedelta(days=date_tolerance_days)
        search_end = end_date + timedelta(days=date_tolerance_days)
        params["from_date"] = search_start.strftime("%Y-%m-%d")
        params["to_date"] = search_end.strftime("%Y-%m-%d")

    logger.info("Fetching bank transactions for account %s", bank_account_id)
    bank_txs = books_client.bank_transactions.list_all(params=params)
    withdrawals = _extract_withdrawals(bank_txs)

    payment_params: Dict[str, Any] = {"vendor_id": vendor_id}
    if start_date and end_date:
        payment_params["from_date"] = start_date.strftime("%Y-%m-%d")
        payment_params["to_date"] = end_date.strftime("%Y-%m-%d")

    logger.info("Fetching vendor payments for vendor %s", vendor_id)
    vendor_payments = books_client.vendor_payments.list_all(params=payment_params)

    parsed_withdrawals = [
        {
            "id": tx.get("transaction_id") or tx.get("id"),
            "date": parse_date(tx.get("date")),
            "amount": get_abs_amount(tx),
            "ref": get_bank_reference(tx, bank_account_id),
            "raw": tx,
        }
        for tx in withdrawals
    ]
    parsed_payments = []
    for p in vendor_payments:
        try:
            p_amount = float(p.get("amount", 0.0))
        except (ValueError, TypeError):
            p_amount = 0.0
        parsed_payments.append({
            "id": p.get("payment_id") or p.get("id"),
            "date": parse_date(p.get("date")),
            "amount": p_amount,
            "ref": p.get("reference_number"),
            "raw": p,
        })

    exact, strong, weak, matched_bank, matched_pay = _run_three_pass_match(
        parsed_withdrawals, "id", parsed_payments, "id",
        date_tolerance_days, amount_tolerance,
    )

    return {
        "exact_matches": exact,
        "strong_matches": strong,
        "weak_matches": weak,
        "unmatched_bank_transactions": [w["raw"] for w in parsed_withdrawals if w["id"] not in matched_bank],
        "unmatched_vendor_payments": [p["raw"] for p in parsed_payments if p["id"] not in matched_pay],
    }


def match_bank_with_vendor_ledger(
    books_client: Any,
    bank_account_id: str,
    vendor_ledger_path: str,
    date_tolerance_days: int = 7,
    amount_tolerance: float = 0.0,
) -> Dict[str, Any]:
    """
    Matches Bank Account withdrawals (Zoho Books) with receipt entries in a local vendor ledger file.
    Date range is auto-inferred from the ledger metadata.
    """
    metadata = get_ledger_metadata(vendor_ledger_path)
    start_date = parse_date(metadata.get("start_date"))
    end_date = parse_date(metadata.get("end_date"))

    params: Dict[str, Any] = {"account_id": bank_account_id}
    if start_date and end_date:
        search_start = start_date - timedelta(days=date_tolerance_days)
        search_end = end_date + timedelta(days=date_tolerance_days)
        params["from_date"] = search_start.strftime("%Y-%m-%d")
        params["to_date"] = search_end.strftime("%Y-%m-%d")

    bank_txs = books_client.bank_transactions.list_all(params=params)
    withdrawals = _extract_withdrawals(bank_txs)

    ledger_entries = clean_ledger_file(vendor_ledger_path)
    ledger_receipts = [
        e for e in ledger_entries
        if e.get("credit_amount", 0.0) > 0.0 or str(e.get("document_type")).lower() == "receipt"
    ]

    parsed_withdrawals = [
        {
            "id": tx.get("transaction_id") or tx.get("id"),
            "date": parse_date(tx.get("date")),
            "amount": get_abs_amount(tx),
            "ref": get_bank_reference(tx, bank_account_id),
            "raw": tx,
        }
        for tx in withdrawals
    ]
    parsed_receipts = [
        {
            "id": r.get("id") or r.get("transaction_no"),
            "date": parse_date(r.get("date")),
            "amount": r.get("credit_amount", 0.0),
            "ref": r.get("transaction_reference") or r.get("transaction_no"),
            "raw": r,
        }
        for r in ledger_receipts
    ]

    exact, strong, weak, matched_bank, matched_rec = _run_three_pass_match(
        parsed_withdrawals, "id", parsed_receipts, "id",
        date_tolerance_days, amount_tolerance,
    )

    return {
        "exact_matches": exact,
        "strong_matches": strong,
        "weak_matches": weak,
        "unmatched_bank_transactions": [w["raw"] for w in parsed_withdrawals if w["id"] not in matched_bank],
        "unmatched_ledger_receipts": [r["raw"] for r in parsed_receipts if r["id"] not in matched_rec],
    }
