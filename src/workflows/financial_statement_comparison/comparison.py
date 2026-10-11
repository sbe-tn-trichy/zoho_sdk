"""Exact-cell comparisons with explicit Books account or section mappings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence
import json
import re

import requests

from workflows.core.matching import to_finite_decimal

KEYS = {"profitandloss": "schedule_profit_and_loss", "balancesheet": "schedule_balance_sheet"}


@dataclass(frozen=True)
class ComparisonLine:
    label: str
    cell: str
    sheet_amount: Decimal
    books_amount: Decimal | None
    difference: Decimal | None
    status: str
    source: str


def fetch_schedule_reports(books: Any, *, from_date: str, to_date: str,
                           excluded_location_id: str,
                           include_opening_balance_sheet: bool = False) -> dict[str, Mapping[str, Any]]:
    """Read each schedule once with a verified branch exclusion and explicit FY."""
    if date.fromisoformat(from_date) > date.fromisoformat(to_date):
        raise ValueError("Invalid date range")
    if not excluded_location_id.strip():
        raise ValueError("An excluded location ID is required")
    rule = json.dumps({"columns": [{"index": 1, "field": "location_name",
        "value": [excluded_location_id], "comparator": "not_in", "group": "branch"}],
        "criteria_string": "1"})
    params = dict(from_date=from_date, to_date=to_date, rule=rule)
    reports = {"profitandloss": books.reports.profit_and_loss_schedule_format(**params),
               "balancesheet": books.reports.balance_sheet_schedule_format(**params)}
    if include_opening_balance_sheet:
        opening_date = (date.fromisoformat(from_date) - timedelta(days=1)).isoformat()
        reports["balancesheet-opening"] = books.reports.balance_sheet_schedule_format(
            from_date=opening_date, to_date=opening_date, rule=rule)
    return reports


def read_sheet_cells(spreadsheet_id: str, cells: Sequence[str], *, access_token: str,
                     session: Any = requests) -> dict[str, Any]:
    """Read exact qualified A1 cells using the caller's Google OAuth token."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id) or not access_token:
        raise ValueError("A spreadsheet ID and Google OAuth token are required")
    response = session.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"ranges": list(cells), "valueRenderOption": "UNFORMATTED_VALUE"}, timeout=30)
    response.raise_for_status()
    ranges = response.json().get("valueRanges", [])
    if len(ranges) != len(cells):
        raise ValueError("Google Sheets did not return every requested cell")
    result = {}
    for cell, entry in zip(cells, ranges):
        values = entry.get("values")
        if not values or len(values) != 1 or len(values[0]) != 1:
            raise ValueError(f"Missing or non-scalar sheet cell: {cell}")
        result[cell] = values[0][0]
    return result


def _amount(value: Any) -> Decimal:
    amount = to_finite_decimal(value, allow_commas=True)
    if amount is None:
        raise ValueError(f"Invalid financial amount: {value!r}")
    return amount


def _nodes(nodes: Sequence[Mapping[str, Any]], path: tuple[str, ...] = ()):
    for node in nodes:
        current = path + (node["name"],)
        if not node.get("section"):
            yield node, current
        yield from _nodes(node.get("account_transactions", []), current)


def compare_statement_cells(cells: Mapping[str, Any], reports: Mapping[str, Mapping[str, Any]],
                            mappings: Sequence[Mapping[str, Any]], *,
                            tolerance: Decimal = Decimal("1")) -> list[ComparisonLine]:
    """Compare every mapped cell; unknown sources remain visible as UNMAPPED.

    Account terms use their own total. Set include_children explicitly for a
    schedule parent subtotal. Repeated section closing rows are never summed.
    Section terms use an exact name path; multipliers allow reviewed netting.
    """
    tolerance = _amount(tolerance)
    if tolerance < 0:
        raise ValueError("Tolerance must be non-negative")
    rows = []
    seen = set()
    for mapping in mappings:
        cell = mapping["cell"]
        if cell in seen:
            raise ValueError(f"Duplicate source cell: {cell}")
        seen.add(cell)
        filed = _amount(cells[cell])
        terms = mapping.get("terms", [])
        if mapping.get("remaining_expense_path"):
            if terms:
                raise ValueError("Remaining expense mapping cannot also specify terms")
            scope = tuple(mapping["remaining_expense_path"])
            candidates = list(_nodes(reports["profitandloss"][KEYS["profitandloss"]]))
            if sum(path == scope for _, path in candidates) != 1:
                raise ValueError("Remaining expense scope must identify one schedule section")
            assigned = [term for other in mappings if other is not mapping
                        for term in other.get("terms", []) if term["report"] == "profitandloss"]
            terms = []
            account_ids = set()
            for node, path in candidates:
                if path[:len(scope)] != scope or not node.get("account_id"):
                    continue
                if any(("name" in term and node["name"] == term["name"]) or
                       ("account_id" in term and str(node["account_id"]) == term["account_id"]) or
                       ("path" in term and path[:len(term["path"])] == tuple(term["path"]))
                       for term in assigned):
                    continue
                account_id = str(node["account_id"])
                if account_id in account_ids:
                    raise ValueError(f"Duplicate remaining expense account: {account_id}")
                account_ids.add(account_id)
                terms.append({"report": "profitandloss", "account_id": account_id})
        total = Decimal()
        sources = []
        missing = []
        for term in terms:
            if sum(key in term for key in ("path", "account_id", "name")) != 1:
                raise ValueError("A Books term needs exactly one path, account_id or name")
            period = term.get("period", "current")
            if period not in ("current", "opening") or (period == "opening" and term["report"] != "balancesheet"):
                raise ValueError("Opening-period terms require a balance-sheet source")
            report = reports[term["report"] + ("-opening" if period == "opening" else "")]
            candidates = list(_nodes(report[KEYS[term["report"]]]))
            matches = [node for node, path in candidates if
                (path == tuple(term["path"]) if "path" in term else
                 str(node.get("account_id", "")) == term["account_id"] if "account_id" in term else
                 node["name"] == term["name"])]
            source = str(term.get("account_id") or term.get("name") or " / ".join(term.get("path", [])))
            if mapping.get("remaining_expense_path") and len(matches) == 1:
                source = matches[0]["name"] + " (" + f"{_amount(matches[0]['total']):,.2f}" + ")"
            if term["report"] == "balancesheet" and report.get("page_context", {}).get("to_date"):
                source += " (as of " + report["page_context"]["to_date"] + ")"
            if not matches:
                missing.append(source)
                continue
            if len(matches) != 1:
                raise ValueError(f"Ambiguous Books source: {source}")
            node = matches[0]
            field = "total_sub_account" if term.get("include_children") and node.get("is_child_present") else "total"
            total += _amount(node[field]) * _amount(term.get("multiplier", 1))
            sources.append(source)
        mapped = bool(terms) and not missing
        if mapping.get("note"):
            sources.append(mapping["note"])
        difference = total - filed if mapped else None
        status = "MATCH" if mapped and abs(difference) <= tolerance else "DIFFERENCE" if mapped else "UNMAPPED"
        rows.append(ComparisonLine(mapping["label"], cell, filed, total if mapped else None,
            difference, status, "; ".join(sources + ["Missing: " + x for x in missing]) or
            mapping.get("note", "Needs reviewed ledger mapping")))
    return rows


def validate_statement_totals(cells: Mapping[str, Any], groups: Sequence[Mapping[str, Any]]) -> None:
    """Verify source line sums, and require the two sides of each statement to balance."""
    totals: dict[str, list[Decimal]] = {}
    for group in groups:
        actual = _amount(cells[group["total_cell"]])
        if abs(sum((_amount(cells[cell]) for cell in group["cells"]), Decimal()) - actual) > Decimal("0.01"):
            raise ValueError(f"Sheet line sum does not agree with {group['total_cell']}")
        totals.setdefault(group["statement"], []).append(actual)
    for statement, amounts in totals.items():
        if len(amounts) != 2 or abs(amounts[0] - amounts[1]) > Decimal("0.01"):
            raise ValueError(f"Sheet {statement} does not balance")


def render_comparison(rows: Sequence[ComparisonLine], *, source_url: str,
                      from_date: str, to_date: str, provenance: str) -> str:
    """Render amounts and qualifications without changing either source."""
    def escaped(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    def mismatch_group(row: ComparisonLine) -> str:
        # The source workbook has liabilities in B and assets in D.
        sheet, _, cell = row.cell.rpartition("!")
        if sheet.strip("'") == "Balance Sheet":
            if cell.startswith("B"):
                return "Liabilities and equities"
            if cell.startswith("D"):
                return "Assets"
        return "Profit and loss / other lines"

    def append_table(group: Sequence[ComparisonLine]) -> None:
        text.extend(["| Line | Sheet cell | Sheet | Books | Difference | Status | Books source / qualification |",
                     "|---|---|---:|---:|---:|---|---|"])
        for row in group:
            amounts = [f"{value:,.2f}" if value is not None else "—" for value in
                       (row.sheet_amount, row.books_amount, row.difference)]
            text.append("| " + " | ".join(map(escaped, [row.label, row.cell, *amounts, row.status, row.source])) + " |")
        text.append("")
    text = ["# Google Sheet versus Zoho Books schedules", "",
        f"Source: [{source_url}]({source_url})", f"Period: {from_date} to {to_date}; accrual; INR.",
        f"Data: {provenance}",
        "Endpoints: reports/scheduleprofitandloss and reports/schedulebalancesheet.",
        "Difference = Books minus sheet. Branch rule echo is verified; this alone does not prove transaction-level scope.",
        "Mappings reflect disclosed account classifications; differences require accounting review.", ""]
    for status, title in (("DIFFERENCE", "Mismatches"), ("UNMAPPED", "Unmapped lines"), ("MATCH", "Matches")):
        group = [row for row in rows if row.status == status]
        text.extend([f"## {title} ({len(group)})", ""])
        if not group:
            text.extend(["None.", ""])
            continue
        if status == "DIFFERENCE":
            for category in ("Liabilities and equities", "Assets", "Profit and loss / other lines"):
                subgroup = [row for row in group if mismatch_group(row) == category]
                if subgroup:
                    text.extend([f"### {category} ({len(subgroup)})", ""])
                    append_table(subgroup)
        else:
            append_table(group)
    return "\n".join(text) + "\n"
