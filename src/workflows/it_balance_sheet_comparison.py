"""Compare filed balance-sheet cells with a dated Zoho Books balance sheet."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class BalanceSheetLine:
    label: str
    filed_cell: str
    account_ids: tuple[str, ...] = ()
    books_path: tuple[str, ...] = ()
    books_paths: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class BalanceSheetDifference:
    label: str
    filed_cell: str
    filed: Decimal
    books: Decimal | None
    difference: Decimal | None
    status: str
    books_source: str


def _amount(value: Any, label: str) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid amount for {label}: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"Non-finite amount for {label}")
    return amount


def _report_nodes(report: Mapping[str, Any], to_date: str) -> list[Mapping[str, Any]]:
    if report.get("code") != 0:
        raise ValueError(f"Books balance sheet failed: {report.get('message', report.get('code'))}")
    context = report.get("page_context")
    if not isinstance(context, Mapping) or context.get("to_date") != to_date or context.get("cash_based") != "false":
        raise ValueError("Books did not return the requested as-of date and accrual basis")
    nodes = report.get("balance_sheet")
    if not isinstance(nodes, list):
        raise ValueError("Books balance_sheet rows are missing")
    return nodes


def _index_nodes(nodes: Sequence[Mapping[str, Any]]) -> tuple[dict[str, tuple[Decimal, str]], dict[tuple[str, ...], Decimal]]:
    accounts: dict[str, tuple[Decimal, str]] = {}
    paths: dict[tuple[str, ...], Decimal] = {}

    def visit(children: Sequence[Mapping[str, Any]], parent: tuple[str, ...]) -> None:
        for node in children:
            name = str(node.get("name") or "")
            path = (*parent, name)
            if "total" not in node:
                raise ValueError(f"Books amount missing at {' / '.join(path)}")
            paths[path] = _amount(node["total"], " / ".join(path))
            account_id = str(node.get("account_id") or "")
            if account_id:
                if account_id in accounts:
                    raise ValueError(f"Duplicate Books account ID: {account_id}")
                accounts[account_id] = (paths[path], name)
            descendants = node.get("account_transactions") or []
            if not isinstance(descendants, list):
                raise ValueError(f"Invalid Books children at {' / '.join(path)}")
            visit(descendants, path)

    visit(nodes, ())
    return accounts, paths


def compare_balance_sheet(
    report: Mapping[str, Any], *, to_date: str, filed_cells: Mapping[str, Any],
    lines: Sequence[BalanceSheetLine], tolerance: Decimal = Decimal("1.00"),
) -> list[BalanceSheetDifference]:
    """Compare reviewed cell mappings; unclassified lines remain explicit."""
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    accounts, paths = _index_nodes(_report_nodes(report, to_date))
    if "B58" in filed_cells and "D58" in filed_cells and (
        abs(_amount(filed_cells["B58"], "B58") - _amount(filed_cells["D58"], "D58")) > tolerance
    ):
        raise ValueError("Filed balance sheet does not balance at row 58")
    seen: set[str] = set()
    result: list[BalanceSheetDifference] = []
    for line in lines:
        if line.filed_cell in seen:
            raise ValueError(f"Duplicate filed cell: {line.filed_cell}")
        seen.add(line.filed_cell)
        if line.filed_cell not in filed_cells:
            raise ValueError(f"Missing filed cell: {line.filed_cell}")
        if line.books_path and line.books_paths:
            raise ValueError(f"Choose one path form for {line.label}")
        filed = _amount(filed_cells[line.filed_cell], line.filed_cell)
        if line.account_ids:
            missing = set(line.account_ids) - set(accounts)
            if missing:
                raise ValueError(f"Missing Books IDs for {line.label}: {', '.join(sorted(missing))}")
            books = sum((accounts[account_id][0] for account_id in line.account_ids), Decimal())
            sources = [
                f"{account_id} ({accounts[account_id][1]})" for account_id in line.account_ids
            ]
        else:
            books = Decimal()
            sources = []
        for path in ((line.books_path,) if line.books_path else line.books_paths):
            if path not in paths:
                raise ValueError(f"Missing Books path: {' / '.join(path)}")
            books += paths[path]
            sources.append(" / ".join(path))
        if not sources:
            books = None
            source = "unmapped"
        else:
            source = "; ".join(sources)
        difference = books - filed if books is not None else None
        status = "UNMAPPED" if books is None else ("MATCH" if abs(difference) <= tolerance else "DIFFERENCE")
        result.append(BalanceSheetDifference(line.label, line.filed_cell, filed, books, difference, status, source))
    return result


def write_comparison_csv(rows: Sequence[BalanceSheetDifference], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("filed_line", "filed_cell", "filed_inr", "books_inr", "books_minus_filed_inr", "status", "books_source"))
        for row in rows:
            writer.writerow((row.label, row.filed_cell, row.filed, row.books, row.difference, row.status, row.books_source))
