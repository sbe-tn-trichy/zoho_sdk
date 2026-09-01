"""Higher-level helper functions for Zoho Books bank account operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

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
