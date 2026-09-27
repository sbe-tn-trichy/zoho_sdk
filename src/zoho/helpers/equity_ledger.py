"""Collect detailed Zoho Books ledger rows for every equity account."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, TypedDict


class EquityLedgerEntry(TypedDict):
    account_id: str
    account_name: str
    location_name: str
    transaction: Mapping[str, Any]


def resolve_excluded_location_name(books_client: Any, excluded_location_id: str) -> str:
    """Resolve a Books branch ID to its unique register location name."""
    if not excluded_location_id or not excluded_location_id.strip():
        raise ValueError("excluded_location_id is required")
    locations = books_client.locations.list_all(resource_key="locations")
    matches = [
        location for location in locations
        if str(location.get("location_id") or "") == excluded_location_id
    ]
    if len(matches) != 1 or not str(matches[0].get("location_name") or "").strip():
        raise ValueError("Excluded Books location ID does not resolve uniquely")
    excluded_name = str(matches[0]["location_name"]).strip()
    if sum(str(location.get("location_name") or "").strip() == excluded_name for location in locations) != 1:
        raise ValueError("Excluded Books location name is ambiguous")
    return excluded_name


def fetch_equity_general_ledger(
    books_client: Any,
    *,
    from_date: str,
    to_date: str,
    excluded_location_id: str,
    per_page: int = 500,
) -> list[EquityLedgerEntry]:
    """Read all equity account registers, excluding one Books location.

    Zoho's public register API works per account. The web report's branch rule
    uses an ID, while register rows expose a location name, so the ID is first
    resolved against the Books locations list. Ambiguous or missing branch data
    fails closed rather than silently widening the report scope.
    """
    try:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("from_date and to_date must be ISO dates") from exc
    if start > end:
        raise ValueError("from_date must not be after to_date")
    if not excluded_location_id or not excluded_location_id.strip():
        raise ValueError("excluded_location_id is required")
    if per_page < 1:
        raise ValueError("per_page must be positive")

    excluded_name = resolve_excluded_location_name(books_client, excluded_location_id)

    accounts: dict[str, str] = {}
    for status in ("AccountType.Active", "AccountType.Inactive"):
        for account in books_client.chart_of_accounts.list_all(params={"filter_by": status}):
            if str(account.get("account_type") or "").casefold() != "equity":
                continue
            account_id = str(account.get("account_id") or "").strip()
            account_name = str(account.get("account_name") or "").strip()
            if not account_id or not account_name:
                raise ValueError("Equity account is missing its ID or name")
            if account_id in accounts and accounts[account_id] != account_name:
                raise ValueError(f"Conflicting equity account name for {account_id}")
            accounts[account_id] = account_name

    entries: list[EquityLedgerEntry] = []
    account_ids = tuple(accounts)
    if not account_ids:
        return entries
    for transaction in books_client.registers.iter_transactions_for_accounts(
            account_ids,
            from_date=from_date,
            to_date=to_date,
            per_page=per_page,
            cash_based=False,
    ):
        account_id = str(transaction.get("account_id") or "")
        if account_id not in accounts:
            raise ValueError("Equity register returned an account outside the requested equity IDs")
        branch = transaction.get("branch")
        if not isinstance(branch, Mapping):
            raise ValueError("Equity register row is missing branch details")
        location_name = str(branch.get("location_name") or "").strip()
        if not location_name:
            raise ValueError("Equity register row is missing location_name")
        if location_name == excluded_name:
            continue
        entries.append({
            "account_id": account_id,
            "account_name": accounts[account_id],
            "location_name": location_name,
            "transaction": transaction,
        })
    return entries
