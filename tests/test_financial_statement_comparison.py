from decimal import Decimal
from unittest.mock import Mock
import json

import pytest

from workflows.financial_statement_comparison import (
    compare_statement_cells, read_sheet_cells, validate_statement_totals, fetch_schedule_reports,
    ComparisonLine, render_comparison,
)


def test_report_groups_statuses_and_handles_empty_groups():
    rows = [ComparisonLine("Matched", "B1", Decimal(10), Decimal(10), Decimal(0), "MATCH", "Source"),
            ComparisonLine("Unknown", "B2", Decimal(10), None, None, "UNMAPPED", "Needs mapping"),
            ComparisonLine("Different", "B3", Decimal(10), Decimal(12), Decimal(2), "DIFFERENCE", "Account | note")]
    kwargs = dict(source_url="https://example.com", from_date="2024-04-01",
                  to_date="2025-03-31", provenance="Saved snapshot")
    report = render_comparison(rows, **kwargs)
    assert report.index("## Mismatches (1)") < report.index("Different") < report.index("## Unmapped lines (1)")
    assert report.index("Unknown") < report.index("## Matches (1)") < report.index("Matched")
    assert "Account \\| note" in report
    assert report.count("| Line |") == 3
    empty = render_comparison([], **kwargs)
    assert empty.count("None.") == 3
    assert "## Matches (0)" in empty


def test_mismatches_split_balance_sheet_sides_without_misclassifying_pnl_stock():
    rows = [ComparisonLine(label, cell, Decimal(10), Decimal(12), Decimal(2), "DIFFERENCE", "Inventories")
            for label, cell in (("Opening stock", "'Trading & P&L A/c'!B4"),
                                ("Capital", "'Balance Sheet'!B5"),
                                ("Fixed assets", "'Balance Sheet'!D4"))]
    report = render_comparison(rows, source_url="https://example.com", from_date="2024-04-01",
                               to_date="2025-03-31", provenance="Saved snapshot")
    assert report.index("### Liabilities and equities (1)") < report.index("Capital") < report.index("### Assets (1)")
    assert report.index("Fixed assets") < report.index("### Profit and loss / other lines (1)") < report.index("Opening stock")
    assert report.count("| Line |") == 3


def test_remaining_expenses_exclude_named_lines_and_parent_subtotals():
    report = {"profitandloss": {"schedule_profit_and_loss": [{"name": "Expenses", "total": 30,
        "account_transactions": [
            {"name": "Named", "account_id": "1", "total": 10},
            {"name": "Office", "account_id": "2", "total": 12, "total_sub_account": 20, "is_child_present": True},
            {"name": "Child", "account_id": "3", "total": 8},
            {"name": "Office", "account_id": "2", "total": 12, "section": True}]}]}}
    mappings = [{"label": "Other", "cell": "B2", "remaining_expense_path": ["Expenses"]},
                {"label": "Named", "cell": "B1", "terms": [{"report": "profitandloss", "name": "Named"}]}]
    row = compare_statement_cells({"B1": 10, "B2": 20}, report, mappings)[0]
    assert row.status == "MATCH"
    assert "Office (12.00)" in row.source and "Child (8.00)" in row.source
    assert "Named" not in row.source
    mappings[0]["remaining_expense_path"] = ["Missing"]
    with pytest.raises(ValueError, match="scope"):
        compare_statement_cells({"B1": 10, "B2": 20}, report, mappings)


def fixture_report():
    return {"profitandloss": {"schedule_profit_and_loss": [{"name": "Revenue", "total": 15,
        "account_transactions": [
            {"name": "Sales", "account_id": "1", "total": 10, "total_sub_account": 15, "is_child_present": True},
            {"name": "Child", "account_id": "2", "total": 5},
            {"name": "Sales", "account_id": "1", "total": 10, "section": True},
        ]}]}}


def test_own_totals_skip_section_closing_rows():
    mapping = [{"label": "Sales", "cell": "B1", "terms": [
        {"report": "profitandloss", "account_id": "1"},
        {"report": "profitandloss", "account_id": "2"}]}]
    row = compare_statement_cells({"B1": 15}, fixture_report(), mapping)[0]
    assert row.books_amount == 15
    assert row.status == "MATCH"
    mapping[0]["terms"] = [{"report": "profitandloss", "name": "Sales", "include_children": True}]
    assert compare_statement_cells({"B1": 15}, fixture_report(), mapping)[0].books_amount == 15


def test_missing_is_unmapped_not_zero():
    rows = compare_statement_cells({"B1": 0}, fixture_report(), [{"label": "Unknown", "cell": "B1",
        "terms": [{"report": "profitandloss", "name": "Unknown"}]}])
    assert rows[0].status == "UNMAPPED"
    assert rows[0].books_amount is None


def test_opening_inventories_use_prior_day_and_same_scope():
    books = Mock()
    fetch_schedule_reports(books, from_date="2024-04-01", to_date="2025-03-31",
        excluded_location_id="excluded", include_opening_balance_sheet=True)
    calls = books.reports.balance_sheet_schedule_format.call_args_list
    assert len(calls) == 2
    assert calls[1].kwargs["from_date"] == "2024-03-31"
    assert calls[1].kwargs["to_date"] == "2024-03-31"
    assert calls[1].kwargs["rule"] == calls[0].kwargs["rule"]


def test_opening_mapping_does_not_use_closing_inventories():
    def balance(amount, as_of):
        return {"page_context": {"to_date": as_of}, "schedule_balance_sheet": [
            {"name": "Inventories", "total": amount}]}
    reports = {"balancesheet": balance(50, "2025-03-31"),
               "balancesheet-opening": balance(20, "2024-03-31")}
    mapping = [{"label": "Opening stock", "cell": "B1", "terms": [
        {"report": "balancesheet", "period": "opening", "path": ["Inventories"]}]}]
    row = compare_statement_cells({"B1": 20}, reports, mapping)[0]
    assert row.status == "MATCH"
    assert row.books_amount == 20
    assert "2024-03-31" in row.source
    del reports["balancesheet-opening"]
    with pytest.raises(KeyError, match="balancesheet-opening"):
        compare_statement_cells({"B1": 20}, reports, mapping)


def test_opening_period_rejects_pnl_source():
    with pytest.raises(ValueError, match="balance-sheet"):
        compare_statement_cells({"B1": 20}, fixture_report(), [{"label": "x", "cell": "B1", "terms": [
            {"report": "profitandloss", "period": "opening", "name": "Sales"}]}])


def test_default_opening_stock_uses_requested_31_march_2025():
    from pathlib import Path
    config = json.loads((Path(__file__).resolve().parents[1] /
        "examples/financial_statement_fy2425.mapping.json").read_text(encoding="utf-8"))
    line = next(line for line in config["lines"] if line["label"].endswith(": Opening Stock"))
    assert line["terms"][0]["period"] == "current"
    assert config["to_date"] == "2025-03-31"
    inventories = {"name": "b. Inventories", "total": "7084911.25"}
    reports = {"balancesheet": {"page_context": {"to_date": config["to_date"]},
        "schedule_balance_sheet": [{"name": "ASSETS", "account_transactions": [
            {"name": "2. Current Assets", "account_transactions": [inventories]}]}]}}
    row = compare_statement_cells({line["cell"]: "12240062.93"}, reports, [line])[0]
    assert row.books_amount == Decimal("7084911.25")
    assert row.difference == Decimal("-5155151.68")
    assert "as of 2025-03-31" in row.source


def test_audited_profit_is_compared_before_tax():
    from pathlib import Path
    config = json.loads((Path(__file__).resolve().parents[1] /
        "examples/financial_statement_fy2425.mapping.json").read_text(encoding="utf-8"))
    line = next(line for line in config["lines"] if line["cell"] == "'Trading & P&L A/c'!B20")
    reports = {"profitandloss": {"schedule_profit_and_loss": [
        {"name": "IX. Profit before tax (VII - VIII)", "total": "625790.78"},
        {"name": "XV. Profit (Loss) for the period (XI + XIV)", "total": "422007.78"}]}}
    row = compare_statement_cells({line["cell"]: "640835.77"}, reports, [line])[0]
    assert row.books_amount == Decimal("625790.78")
    assert row.difference == Decimal("-15044.99")
    assert "before income tax" in row.source


@pytest.mark.parametrize("amount", ["NaN", "Infinity", None, True])
def test_invalid_source_amounts(amount):
    with pytest.raises(ValueError, match="Invalid financial amount"):
        compare_statement_cells({"B1": amount}, fixture_report(), [{"label": "x", "cell": "B1"}])


def test_ambiguous_names_and_duplicate_cells():
    report = fixture_report()
    report["profitandloss"]["schedule_profit_and_loss"][0]["account_transactions"].append(
        {"name": "Sales", "account_id": "3", "total": 2})
    line = {"label": "Sales", "cell": "B1", "terms": [{"report": "profitandloss", "name": "Sales"}]}
    with pytest.raises(ValueError, match="Ambiguous"):
        compare_statement_cells({"B1": 10}, report, [line])
    with pytest.raises(ValueError, match="Duplicate"):
        compare_statement_cells({"B1": 0}, fixture_report(), [{"label": "x", "cell": "B1"}] * 2)


def test_sheet_reads_exact_ranges_and_rejects_blank():
    session = Mock()
    session.get.return_value.json.return_value = {"valueRanges": [{"values": [[15]]}]}
    assert read_sheet_cells("abc", ["'P&L'!B1"], access_token="test", session=session) == {"'P&L'!B1": 15}
    assert session.get.call_args.kwargs["params"]["ranges"] == ["'P&L'!B1"]
    session.get.return_value.json.return_value = {"valueRanges": [{}]}
    with pytest.raises(ValueError, match="Missing"):
        read_sheet_cells("abc", ["B1"], access_token="test", session=session)


def test_source_total_checks():
    checks = [{"statement": "bs", "cells": ["B1"], "total_cell": "B2"},
              {"statement": "bs", "cells": ["D1"], "total_cell": "D2"}]
    validate_statement_totals({"B1": 5, "B2": 5, "D1": 5, "D2": 5}, checks)
    with pytest.raises(ValueError, match="line sum"):
        validate_statement_totals({"B1": 5, "B2": 6, "D1": 5, "D2": 5}, checks)
    with pytest.raises(ValueError, match="does not balance"):
        validate_statement_totals({"B1": 5, "B2": 5, "D1": 6, "D2": 6}, checks)


def test_saved_app_replays_without_auth_or_network(tmp_path, monkeypatch):
    from apps import compare_statement_sheet as app
    monkeypatch.setattr(app, "get_books_client", lambda: pytest.fail("Offline replay constructed a client"))
    monkeypatch.setattr(app, "read_sheet_cells", lambda *a, **k: pytest.fail("Offline replay read live Sheets"))
    config = {"spreadsheet_id": "abc", "source_url": "https://docs.google.com/spreadsheets/d/abc/edit",
        "from_date": "2024-04-01", "to_date": "2025-03-31", "excluded_location_id": "excluded",
        "lines": [{"label": "Revenue", "cell": "B1", "terms": [{"report": "profitandloss", "path": ["Revenue"]}]}]}
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(config))
    snapshot = tmp_path / "source.json"
    snapshot.write_text(json.dumps({**{k: config[k] for k in ("spreadsheet_id", "from_date", "to_date")},
                                  "captured_at": "test", "cells": {"B1": 15}}))
    context = {"from_date": config["from_date"], "to_date": config["to_date"], "cash_based": "false",
        "filter_by": "TransactionDate.CustomDate", "rule": {"criteria_string": "1", "columns": [
            {"index": 1, "field": "location_name", "value": ["excluded"], "comparator": "not_in", "group": "branch"}]}}
    for name, key, nodes in [("profitandloss", "schedule_profit_and_loss", [{"name": "Revenue", "total": 15}]),
                             ("balancesheet", "schedule_balance_sheet", [])]:
        (tmp_path / f"schedule{name}.json").write_text(json.dumps({"code": 0, "page_context": context, key: nodes}))
    assert app.main(["--mapping", str(mapping), "--sheet-snapshot", str(snapshot), "--saved", "--output", str(tmp_path)]) == 0
    assert "MATCH" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "comparison.json").read_text())[0]["difference"] == "0"
    context["to_date"] = "2026-03-31"
    (tmp_path / "scheduleprofitandloss.json").write_text(json.dumps({"code": 0, "page_context": context,
        "schedule_profit_and_loss": []}))
    with pytest.raises(ValueError, match="dates or basis"):
        app.main(["--mapping", str(mapping), "--sheet-snapshot", str(snapshot), "--saved", "--output", str(tmp_path)])
