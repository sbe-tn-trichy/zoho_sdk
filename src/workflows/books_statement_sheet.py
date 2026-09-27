"""Prepare exact Google Sheets cell updates from Zoho Books report values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from zoho.helpers import fetch_equity_general_ledger

from workflows.core.matching import to_finite_decimal


@dataclass(frozen=True)
class StatementMapping:
    report: str
    source_path: tuple[str, ...]
    sheet: str
    current_cell: str
    previous_cell: str
    multiplier: Decimal = Decimal("1")
    account_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatementPeriod:
    current_start: str
    current_end: str
    previous_start: str
    previous_end: str


@dataclass(frozen=True)
class EquityMapping:
    account_id: str
    sheet: str
    name_cell: str
    opening_cell: str
    interest_cell: str
    withdrawal_cell: str
    movement_cell: str
    closing_cell: str


def _value_at(payload: Mapping[str, Any], path: Sequence[str]) -> Decimal:
    value: Any = payload
    for part in path:
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f"Missing Books report field: {'/'.join(path)}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Books amount at {'/'.join(path)}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite Books amount at {'/'.join(path)}")
    return result


def _account_total(payload: Mapping[str, Any], report: str, account_ids: Sequence[str]) -> Decimal:
    found: dict[str, Decimal] = {}

    def visit(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            account_id = str(node.get("account_id") or "")
            if account_id in account_ids:
                if account_id in found:
                    raise ValueError(f"Duplicate Books account in report: {account_id}")
                found[account_id] = _value_at(node, ("total",))
            visit(node.get("account_transactions"))

    visit(payload.get("profit_and_loss" if report == "profitandloss" else "balance_sheet"))
    missing = set(account_ids) - set(found)
    if missing:
        raise ValueError(f"Books report is missing account IDs: {', '.join(sorted(missing))}")
    return sum(found.values(), Decimal())


def prepare_updates(
    books: Any,
    periods: StatementPeriod,
    mappings: Sequence[StatementMapping],
    location_ids: Sequence[str] = (),
) -> dict[str, Decimal]:
    """Fetch each distinct report/period once and return qualified A1 cell values.

    Caller owns Google Sheets authentication and applying the returned updates.
    Paths name scalar fields in the Books JSON response; ambiguous account names
    must be resolved to exact report paths in the mapping before running.
    """
    reports: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    updates: dict[str, Decimal] = {}
    for mapping in mappings:
        if not mapping.report or not mapping.sheet or not (mapping.source_path or mapping.account_ids):
            raise ValueError("Every mapping needs a report, source, and sheet")
        if mapping.source_path and mapping.account_ids:
            raise ValueError("Use a report path or account IDs, not both")
        if mapping.report not in {"profitandloss", "balancesheet"}:
            raise ValueError(f"Unsupported Books report: {mapping.report}")
        for start, end, cell in (
            (periods.current_start, periods.current_end, mapping.current_cell),
            (periods.previous_start, periods.previous_end, mapping.previous_cell),
        ):
            key = (mapping.report, start, end)
            if key not in reports:
                params = {
                    "filter_by": "TransactionDate.CustomDate",
                    "from_date": start,
                    "to_date": end,
                    "cash_based": "false",
                    "show_rows": "all",
                }
                if location_ids:
                    params["location_ids"] = ",".join(location_ids)
                response = books.request("GET", f"reports/{mapping.report}", params=params)
                if not isinstance(response, Mapping) or response.get("code") != 0:
                    raise ValueError(f"Books {mapping.report} failed for {start} to {end}")
                context = response.get("page_context") or {}
                if context.get("to_date") != end or context.get("filter_by") != "TransactionDate.CustomDate" or (
                    mapping.report == "profitandloss" and context.get("from_date") != start
                ) or context.get("cash_based") != "false":
                    raise ValueError(f"Books ignored requested dates for {mapping.report}")
                reports[key] = response
            qualified = f"'{mapping.sheet.replace(chr(39), chr(39) * 2)}'!{cell}"
            if qualified in updates:
                raise ValueError(f"Duplicate target cell: {qualified}")
            source = (_account_total(reports[key], mapping.report, mapping.account_ids)
                      if mapping.account_ids else _value_at(reports[key], mapping.source_path))
            updates[qualified] = source * mapping.multiplier
    return updates


def prepare_equity_updates(
    books: Any,
    periods: StatementPeriod,
    mappings: Sequence[EquityMapping],
    *,
    location_ids: Sequence[str],
    excluded_location_id: str,
    account_names: Mapping[str, str],
    interest_account_id: str,
    withdrawal_transaction_types: Sequence[str],
) -> dict[str, Decimal | str]:
    """Prepare owner openings, interest, withdrawals, and residual movements.

    Existing closing-balance formulas are never write targets. Each computed
    closing balance must agree exactly with the location-scoped Books balance
    sheet before any update is returned.
    """
    if not mappings:
        raise ValueError("Equity mappings cannot be empty")
    if not location_ids:
        raise ValueError("Equity updates require location_ids")
    if not excluded_location_id:
        raise ValueError("Equity updates require excluded_location_id")
    if not interest_account_id:
        raise ValueError("Equity updates require interest_account_id")
    if not withdrawal_transaction_types or any(not kind for kind in withdrawal_transaction_types):
        raise ValueError("Equity updates require withdrawal_transaction_types")

    target_cells: set[str] = set()
    report_mappings: list[StatementMapping] = []
    for mapping in mappings:
        if not mapping.account_id or not mapping.sheet:
            raise ValueError("Every equity mapping needs an account ID and sheet")
        if mapping.account_id not in account_names:
            raise ValueError(f"Unknown equity account ID: {mapping.account_id}")
        for cell in (
            mapping.name_cell, mapping.opening_cell, mapping.interest_cell,
            mapping.withdrawal_cell, mapping.movement_cell, mapping.closing_cell,
        ):
            target = f"'{mapping.sheet.replace(chr(39), chr(39) * 2)}'!{cell}"
            if target in target_cells:
                raise ValueError(f"Duplicate equity cell: {target}")
            target_cells.add(target)
        report_mappings.append(StatementMapping(
            report="balancesheet", source_path=(), sheet=mapping.sheet,
            current_cell=mapping.closing_cell, previous_cell=mapping.opening_cell,
            account_ids=(mapping.account_id,),
        ))

    balances = prepare_updates(books, periods, report_mappings, location_ids)
    entries = fetch_equity_general_ledger(
        books, from_date=periods.current_start, to_date=periods.current_end,
        excluded_location_id=excluded_location_id,
    )
    movements = {mapping.account_id: Decimal() for mapping in mappings}
    interest = {mapping.account_id: Decimal() for mapping in mappings}
    withdrawals = {mapping.account_id: Decimal() for mapping in mappings}
    for entry in entries:
        account_id = entry["account_id"]
        if account_id not in movements:
            continue
        transaction = entry["transaction"]
        if "debit" not in transaction or "credit" not in transaction:
            raise ValueError(f"Equity ledger row is missing debit or credit: {account_id}")
        debit = to_finite_decimal(transaction["debit"] or 0, allow_commas=True)
        credit = to_finite_decimal(transaction["credit"] or 0, allow_commas=True)
        if debit is None or credit is None:
            raise ValueError(f"Equity ledger row has invalid debit or credit: {account_id}")
        movements[account_id] += credit - debit
        if str(transaction.get("offset_account_id") or "") == interest_account_id:
            interest[account_id] += credit - debit
        elif str(transaction.get("transaction_type") or "") in withdrawal_transaction_types:
            withdrawals[account_id] += debit

    updates: dict[str, Decimal | str] = {}
    for mapping in mappings:
        prefix = f"'{mapping.sheet.replace(chr(39), chr(39) * 2)}'!"
        opening = balances[prefix + mapping.opening_cell]
        closing = balances[prefix + mapping.closing_cell]
        movement = movements[mapping.account_id]
        interest_amount = interest[mapping.account_id]
        withdrawal_amount = withdrawals[mapping.account_id]
        residual = movement - interest_amount + withdrawal_amount
        if opening + movement != closing:
            raise ValueError(
                f"Equity ledger does not reconcile for {mapping.account_id}: "
                f"{opening} + {movement} != {closing}"
            )
        updates[prefix + mapping.name_cell] = account_names[mapping.account_id]
        updates[prefix + mapping.opening_cell] = opening
        updates[prefix + mapping.interest_cell] = interest_amount
        updates[prefix + mapping.withdrawal_cell] = withdrawal_amount
        updates[prefix + mapping.movement_cell] = residual
    return updates
