"""Match Zoho Books bank-account withdrawals against either:
  - Zoho Books vendor payments (match_ledger_entries)
  - An external vendor ledger file on disk (match_bank_with_vendor_ledger)
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..core.matching import (
    get_bank_reference,
    parse_date,
    reconcile_rows,
    ref_match,
    to_decimal,
)
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
    parsed_right: List[Dict[str, Any]],
    date_tolerance_days: int,
    amount_tolerance: float,
) -> Tuple[Any, ...]:
    """
    Generic 3-pass match between two pre-parsed lists.
    Each item must have date, amount, ref, and raw values. Matching identity is
    its row position, never an optional or duplicated external transaction ID.
    """
    result = reconcile_rows(
        parsed_left,
        parsed_right,
        reference_matches=lambda left, right: ref_match(left.get("ref"), right.get("ref")),
        reference_conflicts=lambda left, right: bool(
            str(left.get("ref") or "").strip()
            and str(right.get("ref") or "").strip()
            and not ref_match(left.get("ref"), right.get("ref"))
        ),
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
    )
    return (
        result["exact_matches"],
        result["strong_matches"],
        result["weak_matches"],
        result["ambiguous_matches"],
        result["matched_left_indices"],
        result["matched_right_indices"],
        result["ambiguous_left_indices"],
        result["ambiguous_right_indices"],
    )


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
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date")
    if start_date:
        params["from_date"] = (start_date - timedelta(days=date_tolerance_days)).strftime("%Y-%m-%d")
    if end_date:
        params["to_date"] = (end_date + timedelta(days=date_tolerance_days)).strftime("%Y-%m-%d")

    logger.info("Fetching bank transactions for account %s", bank_account_id)
    bank_txs = books_client.bank_transactions.list_all(params=params)
    withdrawals = _extract_withdrawals(bank_txs)

    payment_params: Dict[str, Any] = {"vendor_id": vendor_id}
    if start_date:
        payment_params["from_date"] = start_date.strftime("%Y-%m-%d")
    if end_date:
        payment_params["to_date"] = end_date.strftime("%Y-%m-%d")

    logger.info("Fetching vendor payments for vendor %s", vendor_id)
    vendor_payments = books_client.vendor_payments.list_all(params=payment_params)

    parsed_withdrawals = [
        {
            "id": tx.get("transaction_id") or tx.get("id"),
            "date": parse_date(tx.get("date")),
            "amount": abs(to_decimal(tx.get("amount")) or 0),
            "ref": get_bank_reference(tx, bank_account_id),
            "raw": tx,
        }
        for tx in withdrawals
    ]
    parsed_payments = []
    for p in vendor_payments:
        p_amount = to_decimal(p.get("amount"))
        parsed_payments.append({
            "id": p.get("payment_id") or p.get("id"),
            "date": parse_date(p.get("date")),
            "amount": p_amount,
            "ref": p.get("reference_number"),
            "raw": p,
        })

    exact, strong, weak, ambiguous, matched_bank, matched_pay, ambiguous_bank, ambiguous_pay = _run_three_pass_match(
        parsed_withdrawals, parsed_payments,
        date_tolerance_days, amount_tolerance,
    )

    return {
        "exact_matches": exact,
        "strong_matches": strong,
        "weak_matches": weak,
        "ambiguous_matches": ambiguous,
        "unmatched_bank_transactions": [w["raw"] for index, w in enumerate(parsed_withdrawals) if index not in matched_bank | ambiguous_bank],
        "unmatched_vendor_payments": [p["raw"] for index, p in enumerate(parsed_payments) if index not in matched_pay | ambiguous_pay],
    }


def match_bank_with_vendor_ledger(
    books_client: Any,
    bank_account_id: str,
    vendor_ledger_path: str,
    vendor_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    date_tolerance_days: int = 4,
    amount_tolerance: float = 0.01,
) -> Dict[str, Any]:
    """
    Matches Bank Account withdrawals (Zoho Books) with receipt entries in a local vendor ledger file.
    The date range is auto-inferred from ledger metadata unless explicitly
    supplied. ``vendor_id`` is accepted for API symmetry with Books vendor
    payment matching; the supplied ledger file remains the vendor scope.
    """
    metadata = get_ledger_metadata(vendor_ledger_path)
    start_date = start_date or parse_date(metadata.get("start_date"))
    end_date = end_date or parse_date(metadata.get("end_date"))

    params: Dict[str, Any] = {"account_id": bank_account_id}
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date")
    if start_date:
        params["from_date"] = (start_date - timedelta(days=date_tolerance_days)).strftime("%Y-%m-%d")
    if end_date:
        params["to_date"] = (end_date + timedelta(days=date_tolerance_days)).strftime("%Y-%m-%d")

    bank_txs = books_client.bank_transactions.list_all(params=params)
    withdrawals = _extract_withdrawals(bank_txs)

    ledger_entries = clean_ledger_file(vendor_ledger_path)
    ledger_receipts = [
        e for e in ledger_entries
        if (to_decimal(e.get("credit_amount")) or 0) > 0
        or str(e.get("document_type")).lower() == "receipt"
    ]

    parsed_withdrawals = [
        {
            "id": tx.get("transaction_id") or tx.get("id"),
            "date": parse_date(tx.get("date")),
            "amount": abs(to_decimal(tx.get("amount")) or 0),
            "ref": get_bank_reference(tx, bank_account_id),
            "raw": tx,
        }
        for tx in withdrawals
    ]
    parsed_receipts = [
        {
            "id": r.get("id") or r.get("transaction_no"),
            "date": parse_date(r.get("date")),
            "amount": to_decimal(r.get("credit_amount")),
            "ref": r.get("transaction_reference") or r.get("transaction_no"),
            "raw": r,
        }
        for r in ledger_receipts
    ]

    exact, strong, weak, ambiguous, matched_bank, matched_rec, ambiguous_bank, ambiguous_rec = _run_three_pass_match(
        parsed_withdrawals, parsed_receipts,
        date_tolerance_days, amount_tolerance,
    )

    return {
        "exact_matches": exact,
        "strong_matches": strong,
        "weak_matches": weak,
        "ambiguous_matches": ambiguous,
        "unmatched_bank_transactions": [w["raw"] for index, w in enumerate(parsed_withdrawals) if index not in matched_bank | ambiguous_bank],
        "unmatched_ledger_receipts": [r["raw"] for index, r in enumerate(parsed_receipts) if index not in matched_rec | ambiguous_rec],
    }
