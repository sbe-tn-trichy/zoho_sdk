"""Compare filed GSTR-3B turnover with the Books Sales account hierarchy."""

from __future__ import annotations

import csv
import json
from calendar import month_name, monthrange
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, TypedDict


class ComparisonRow(TypedDict):
    period: str
    gstr3b_status: str
    gstr3b_outward_taxable_value: str
    books_sales_total: str
    sales_variance_books_minus_gstr3b: str
    sales_comparison: str
    books_pnl_cost_of_goods_sold: str
    purchase_comparison: str


@dataclass(frozen=True)
class ComparisonConfig:
    sales_account_id: str
    excluded_location_id: str
    tolerance: Decimal = Decimal("1.00")

    def __post_init__(self) -> None:
        if not self.sales_account_id or not self.excluded_location_id:
            raise ValueError("Sales account and excluded location IDs are required")
        if self.tolerance < 0:
            raise ValueError("Tolerance cannot be negative")


FIELDS = list(ComparisonRow.__annotations__)
PURCHASE_NOTE = "NOT_COMPARABLE_GSTR3B_HAS_NO_PURCHASE_TOTAL"


def _amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError("Non-finite amount in source data")
    return amount


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _walk_accounts(nodes: list[dict[str, Any]]):
    for node in nodes:
        if node.get("account_id"):
            yield node
        yield from _walk_accounts(node.get("account_transactions") or [])


def _sales_account_ids(books: Any, root_id: str) -> set[str]:
    accounts = books.chart_of_accounts.list_all()
    if not any(str(account.get("account_id")) == root_id for account in accounts):
        raise ValueError(f"Sales account {root_id} not found in Books")
    ids = {root_id}
    while True:
        expanded = ids | {
            str(account["account_id"])
            for account in accounts
            if str(account.get("parent_account_id") or "") in ids
        }
        if expanded == ids:
            return ids
        ids = expanded


def _pnl_totals(
    books: Any, start: str, end: str, config: ComparisonConfig, sales_ids: set[str]
) -> tuple[Decimal, Decimal]:
    rule = {
        "columns": [{"index": 1, "field": "location_name", "value": [config.excluded_location_id],
                     "comparator": "not_in", "group": "branch"}],
        "criteria_string": "1",
    }
    response = books.request("GET", "reports/profitandloss", params={
        "from_date": start, "to_date": end, "cash_based": "false",
        "is_hierarchy_report": "true", "rule": json.dumps(rule, separators=(",", ":")),
        "show_rows": "all",
    })
    if response.get("code") != 0:
        raise ValueError(f"Books P&L request failed for {start} to {end}")
    context = response.get("page_context") or {}
    columns = (context.get("rule") or {}).get("columns") or []
    if (context.get("from_date") != start or context.get("to_date") != end
            or context.get("cash_based") != "false"
            or not columns or columns[0].get("value") != [config.excluded_location_id]):
        raise ValueError(f"Books did not apply the requested P&L scope for {start} to {end}")
    sections = {
        child.get("name"): child
        for top in response.get("profit_and_loss") or []
        for child in top.get("account_transactions") or []
    }
    if "Operating Income" not in sections or "Cost of Goods Sold" not in sections:
        raise ValueError(f"Books P&L is missing required sections for {start} to {end}")
    income_accounts = list(_walk_accounts(sections["Operating Income"].get("account_transactions") or []))
    present = {str(item["account_id"]) for item in income_accounts}
    if config.sales_account_id not in present:
        raise ValueError(f"Sales account is absent from P&L for {start} to {end}")
    sales = sum((_amount(item["total"]) for item in income_accounts
                 if str(item["account_id"]) in sales_ids), Decimal())
    cogs = _amount(sections["Cost of Goods Sold"]["total"])
    return sales, cogs


def _row(period: str, status: str, taxable: Decimal, sales: Decimal,
         cogs: Decimal, tolerance: Decimal) -> ComparisonRow:
    difference = sales - taxable
    return {
        "period": period,
        "gstr3b_status": status,
        "gstr3b_outward_taxable_value": _money(taxable),
        "books_sales_total": _money(sales),
        "sales_variance_books_minus_gstr3b": _money(difference),
        "sales_comparison": "MATCH" if abs(difference) <= tolerance else "DIFFERENCE",
        "books_pnl_cost_of_goods_sold": _money(cogs),
        "purchase_comparison": PURCHASE_NOTE,
    }


def compare_gstr3b_to_pnl(
    books: Any, return_data: Mapping[str, Any], config: ComparisonConfig
) -> list[ComparisonRow]:
    """Fetch 12 monthly and one FY P&L reports, then compare Sales with GSTR-3B.

    Raises ValueError for incomplete returns, ignored report filters, or monthly/FY
    Books totals that do not reconcile. No output is written by this function.
    """
    try:
        start_year = int(str(return_data["filing_year"]).split("-")[0])
        expected_year = f"{start_year}-{(start_year + 1) % 100:02d}"
        if return_data["filing_year"] != expected_year:
            raise ValueError("Invalid filing year")
        returns = return_data["returns"]
        if not isinstance(returns, list) or len(returns) != 12:
            raise ValueError("Exactly 12 monthly returns are required")
        by_month: dict[str, Mapping[str, Any]] = {}
        for entry in returns:
            key = str(entry["period"]).strip().casefold()
            if key in by_month:
                raise ValueError(f"Duplicate return period: {entry['period']}")
            if entry["filing_status"] != "FILED":
                raise ValueError(f"Return is not filed: {entry['period']}")
            by_month[key] = entry
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Invalid GSTR-3B return structure") from exc

    sales_ids = _sales_account_ids(books, config.sales_account_id)
    rows: list[ComparisonRow] = []
    taxable_total = Decimal()
    monthly_sales = Decimal()
    monthly_cogs = Decimal()
    for offset in range(12):
        year = start_year + (offset + 3) // 12
        month = (offset + 3) % 12 + 1
        period = f"{year}-{month:02d}"
        try:
            entry = by_month.pop(month_name[month].casefold())
            taxable = _amount(entry["table_3_1_supplies"]["outward_taxable_supplies"]["taxable_value"])
        except KeyError as exc:
            raise ValueError(f"Missing or invalid GSTR-3B data for {period}") from exc
        sales, cogs = _pnl_totals(books, f"{period}-01",
                                   f"{period}-{monthrange(year, month)[1]:02d}", config, sales_ids)
        rows.append(_row(period, "FILED", taxable, sales, cogs, config.tolerance))
        taxable_total += taxable
        monthly_sales += sales
        monthly_cogs += cogs
    if by_month:
        raise ValueError(f"Unexpected return periods: {', '.join(by_month)}")
    annual_sales, annual_cogs = _pnl_totals(
        books, f"{start_year}-04-01", f"{start_year + 1}-03-31", config, sales_ids
    )
    if abs(annual_sales - monthly_sales) > Decimal("0.01") or abs(annual_cogs - monthly_cogs) > Decimal("0.01"):
        raise ValueError("Monthly Books P&L totals do not reconcile to the FY report")
    rows.append(_row(f"FY {expected_year}", "12 FILED", taxable_total,
                     annual_sales, annual_cogs, config.tolerance))
    return rows


def write_comparison_csv(rows: list[ComparisonRow], path: Path) -> Path:
    """Write a validated comparison to CSV, replacing an existing report atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
