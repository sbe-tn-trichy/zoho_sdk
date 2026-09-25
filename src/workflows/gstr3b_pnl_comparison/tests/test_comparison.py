import csv
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.gstr3b_pnl_comparison import (
    ComparisonConfig, compare_gstr3b_to_pnl, write_comparison_csv,
)


CONFIG = ComparisonConfig("sales", "excluded", Decimal("1.00"))


def make_data():
    months = [date(2025 + (i + 3) // 12, (i + 3) % 12 + 1, 1).strftime("%B")
              for i in range(12)]
    return {"filing_year": "2025-26", "returns": [
        {"period": month, "filing_status": "FILED",
         "table_3_1_supplies": {"outward_taxable_supplies": {"taxable_value": "100.00"}}}
        for month in months
    ]}


def make_books(*, annual_sales="1200.00", valid_scope=True):
    accounts = [
        {"account_id": "sales", "parent_account_id": ""},
        {"account_id": "child", "parent_account_id": "sales"},
        {"account_id": "grandchild", "parent_account_id": "child"},
        {"account_id": "outside", "parent_account_id": ""},
    ]
    def request(method, endpoint, params):
        assert (method, endpoint) == ("GET", "reports/profitandloss")
        start = params["from_date"]
        annual = start == "2025-04-01" and params["to_date"] == "2026-03-31"
        sales = annual_sales if annual else "100.00"
        return {
            "code": 0,
            "page_context": {
                "from_date": start, "to_date": params["to_date"],
                "cash_based": "false",
                "rule": {"columns": [{"value": ["excluded" if valid_scope else "wrong"]}]},
            },
            "profit_and_loss": [{"account_transactions": [
                {"name": "Operating Income", "account_transactions": [
                    {"account_id": "sales", "total": "10.00" if not annual else "120.00"},
                    {"account_id": "child", "total": "20.00" if not annual else "240.00",
                     "account_transactions": [
                         {"account_id": "grandchild", "total": "70.00" if not annual else
                          str(Decimal(sales) - Decimal("360.00"))}
                     ]},
                    {"account_id": "outside", "total": "5000.00"},
                ]},
                {"name": "Cost of Goods Sold", "total": "60.00" if not annual else "720.00"},
            ]}],
        }
    return SimpleNamespace(chart_of_accounts=SimpleNamespace(list_all=Mock(return_value=accounts)),
                           request=Mock(side_effect=request))


def test_comparison_includes_sales_descendants_and_reconciles_annual(tmp_path):
    books = make_books()
    rows = compare_gstr3b_to_pnl(books, make_data(), CONFIG)
    assert len(rows) == 13
    assert rows[0]["books_sales_total"] == "100.00"
    assert rows[-1]["books_sales_total"] == "1200.00"
    assert rows[-1]["books_pnl_cost_of_goods_sold"] == "720.00"
    assert rows[-1]["sales_comparison"] == "MATCH"
    assert books.request.call_count == 13
    path = write_comparison_csv(rows, tmp_path / "report.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 13


def test_unreconciled_annual_report_raises():
    with pytest.raises(ValueError, match="do not reconcile"):
        compare_gstr3b_to_pnl(make_books(annual_sales="1201.00"), make_data(), CONFIG)


def test_wrong_books_scope_raises():
    with pytest.raises(ValueError, match="did not apply"):
        compare_gstr3b_to_pnl(make_books(valid_scope=False), make_data(), CONFIG)


@pytest.mark.parametrize("change", ["duplicate", "draft", "missing"])
def test_invalid_return_fails_before_writing(change):
    data = make_data()
    if change == "duplicate":
        data["returns"][1]["period"] = "April"
    elif change == "draft":
        data["returns"][1]["filing_status"] = "DRAFT"
    else:
        data["returns"].pop()
    with pytest.raises(ValueError):
        compare_gstr3b_to_pnl(make_books(), data, CONFIG)


def test_negative_tolerance_rejected():
    with pytest.raises(ValueError, match="Tolerance"):
        ComparisonConfig("sales", "excluded", Decimal("-1"))
