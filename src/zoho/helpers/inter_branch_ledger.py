"""Fetch one inter-branch account's detailed Zoho Books ledger."""

from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Mapping, TypedDict

from .equity_ledger import resolve_excluded_location_name


class InterBranchLedgerEntry(TypedDict):
    account_id: str
    location_name: str
    transaction: Mapping[str, Any]


@dataclass(frozen=True)
class InterBranchGeneralLedger:
    account_id: str
    from_date: str
    to_date: str
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal
    is_debit: bool


def fetch_inter_branch_general_ledger(
    books_client: Any,
    *,
    from_date: str,
    to_date: str,
    account_id: str = "1094368000000443474",
    excluded_location_id: str = "1094368000044509446",
 ) -> InterBranchGeneralLedger:
    """Fetch the branch-filtered inter-branch balance via the Books SDK report."""
    try:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("from_date and to_date must be ISO dates") from exc
    if start > end:
        raise ValueError("from_date must not be after to_date")
    if not account_id or not account_id.strip():
        raise ValueError("account_id is required")
    if not excluded_location_id or not excluded_location_id.strip():
        raise ValueError("excluded_location_id is required")
    rule = {"columns": [
        {"index": 1, "field": "account_id", "value": [account_id],
         "comparator": "in", "group": "report"},
        {"index": 2, "field": "location_name", "value": [excluded_location_id],
         "comparator": "not_in", "group": "branch"},
    ], "criteria_string": "( 1 AND 2 )"}
    response = books_client.reports.general_ledger(
        from_date=from_date, to_date=to_date,
        rule=json.dumps(rule, separators=(",", ":")), cash_based=False,
    )
    rows = response["generalledger"]
    if len(rows) != 1 or str(rows[0].get("account_id") or "") != account_id:
        raise ValueError("Books General Ledger did not return exactly the inter-branch account")
    row = rows[0]
    try:
        debit = Decimal(str(row["debit_total"]))
        credit = Decimal(str(row["credit_total"]))
        balance = Decimal(str(row["balance"]))
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("Books General Ledger amounts are invalid") from exc
    if not all(value.is_finite() for value in (debit, credit, balance)):
        raise ValueError("Books General Ledger amounts are non-finite")
    is_debit = row.get("is_debit")
    if not isinstance(is_debit, bool):
        raise ValueError("Books General Ledger balance direction is missing")
    return InterBranchGeneralLedger(account_id, from_date, to_date, debit, credit, balance, is_debit)


def fetch_inter_branch_register_transactions(
    books_client: Any, *, from_date: str, to_date: str,
    account_id: str = "1094368000000443474",
    excluded_location_id: str = "1094368000044509446",
    per_page: int = 500,
) -> list[InterBranchLedgerEntry]:
    """Read raw register postings, which may omit branch-generated balances."""
    if per_page < 1:
        raise ValueError("per_page must be positive")
    excluded_name = resolve_excluded_location_name(books_client, excluded_location_id)
    entries: list[InterBranchLedgerEntry] = []
    for transaction in books_client.registers.iter_transactions(
        account_id, from_date=from_date, to_date=to_date,
        per_page=per_page, cash_based=False,
    ):
        if str(transaction.get("account_id") or "") != account_id:
            raise ValueError("Inter-branch register returned an unexpected account ID")
        branch = transaction.get("branch")
        if not isinstance(branch, Mapping):
            raise ValueError("Inter-branch register row is missing branch details")
        location_name = str(branch.get("location_name") or "").strip()
        if not location_name:
            raise ValueError("Inter-branch register row is missing location_name")
        if location_name != excluded_name:
            entries.append({
                "account_id": account_id,
                "location_name": location_name,
                "transaction": transaction,
            })
    return entries
