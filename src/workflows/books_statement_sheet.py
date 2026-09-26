"""Prepare exact Google Sheets cell updates from Zoho Books report values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


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
    books: Any, periods: StatementPeriod, mappings: Sequence[StatementMapping]
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
                response = books.request("GET", f"reports/{mapping.report}", params={
                    "from_date": start,
                    "to_date": end,
                    "cash_based": "false",
                    "show_rows": "all",
                })
                if not isinstance(response, Mapping) or response.get("code") != 0:
                    raise ValueError(f"Books {mapping.report} failed for {start} to {end}")
                context = response.get("page_context") or {}
                if context.get("to_date") != end or (
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
