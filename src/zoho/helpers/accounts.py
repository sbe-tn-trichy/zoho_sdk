"""Higher-level helper functions for Zoho Books bank account operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger("zoho.helpers.accounts")


def _get_accounts_iterable(accounts_resource: Any) -> Any:
    """Safely obtain iterable over bank accounts."""
    if hasattr(accounts_resource, "list_all") and callable(accounts_resource.list_all):
        res = accounts_resource.list_all(resource_key="bankaccounts")
        if isinstance(res, list):
            return res
    if hasattr(accounts_resource, "list_iter") and callable(accounts_resource.list_iter):
        res = accounts_resource.list_iter(resource_key="bankaccounts")
        if isinstance(res, (list, tuple)) or hasattr(res, "__iter__"):
            return res
    res = accounts_resource.list()
    if isinstance(res, dict):
        return res.get("bankaccounts", res.get("bank_accounts", []))
    if isinstance(res, list):
        return res
    return []


def find_bank_account_by_name(
    books_client: Any,
    account_name: str,
) -> Optional[Dict[str, Any]]:
    """Look up a bank account by case-insensitive account_name."""
    expected = str(account_name or "").strip().casefold()
    if not expected:
        return None

    try:
        accounts = _get_accounts_iterable(books_client.bank_accounts)
        for account in accounts:
            name = str(account.get("account_name") or "").strip().casefold()
            if name == expected:
                return account
    except Exception as exc:
        logger.warning(f"Error querying bank accounts for '{account_name}': {exc}")
        return None

    return None


def fetch_bank_accounts_map(
    books_client: Any,
) -> Dict[str, Dict[str, Any]]:
    """Fetch all bank accounts and index them by case-folded account_name."""
    lookup: Dict[str, Dict[str, Any]] = {}
    try:
        accounts = _get_accounts_iterable(books_client.bank_accounts)
        for account in accounts:
            name = str(account.get("account_name") or "").strip()
            if name:
                lookup[name.casefold()] = account
    except Exception as exc:
        logger.error(f"Error fetching bank accounts map: {exc}")
        raise

    return lookup


def extract_bank_withdrawals(
    transactions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Filter a list of bank transactions down to outflows (withdrawals / debits)."""
    withdrawals: List[Dict[str, Any]] = []
    for tx in transactions:
        amount_val = 0.0
        try:
            amount_val = float(tx.get("amount", 0.0))
        except (ValueError, TypeError):
            pass

        doc_type = str(tx.get("transaction_type") or tx.get("type") or "").lower()
        doc_dc = str(tx.get("debit_or_credit") or "").lower()

        is_withdrawal = (
            amount_val < 0
            or doc_dc == "debit"
            or doc_type in ("expense", "withdrawal", "payment")
        )
        if is_withdrawal:
            withdrawals.append(dict(tx))
    return withdrawals


def extract_bank_deposits(
    transactions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Filter a list of bank transactions down to inflows (deposits / credits / receipts)."""
    deposits: List[Dict[str, Any]] = []
    for tx in transactions:
        amount_val = 0.0
        try:
            amount_val = float(tx.get("amount", 0.0))
        except (ValueError, TypeError):
            pass

        doc_type = str(tx.get("transaction_type") or tx.get("type") or "").lower()
        doc_dc = str(tx.get("debit_or_credit") or "").lower()

        if doc_dc == "debit" or doc_type in ("expense", "withdrawal", "payment") or amount_val < 0:
            continue

        is_deposit = (
            amount_val > 0
            or doc_dc == "credit"
            or doc_type in ("deposit", "refund", "receipt", "income")
        )
        if is_deposit:
            deposits.append(dict(tx))
    return deposits


