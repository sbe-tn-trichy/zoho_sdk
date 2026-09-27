from decimal import Decimal

import pytest

from workflows.it_balance_sheet_comparison import BalanceSheetLine, compare_balance_sheet


def _report():
    return {"code": 0, "page_context": {"to_date": "2025-03-31", "cash_based": "false"},
            "balance_sheet": [{"name": "Assets", "total": "100", "account_transactions": [
                {"name": "Cash", "account_id": "cash", "total": "40"},
                {"name": "Bank", "account_id": "bank", "total": "60"}]}]}


def test_compares_account_groups_and_section_totals():
    lines = [BalanceSheetLine("Funds", "B1", ("cash", "bank")),
             BalanceSheetLine("Assets", "D1", books_path=("Assets",)),
             BalanceSheetLine("Other", "D2")]
    result = compare_balance_sheet(_report(), to_date="2025-03-31",
                                   filed_cells={"B1": 90, "D1": 100, "D2": 5}, lines=lines)
    assert [(item.status, item.difference) for item in result] == [
        ("DIFFERENCE", Decimal("10")), ("MATCH", Decimal("0")), ("UNMAPPED", None)]
    assert result[0].books_source == "cash (Cash); bank (Bank)"


def test_missing_account_and_wrong_date_fail():
    with pytest.raises(ValueError, match="Missing Books IDs"):
        compare_balance_sheet(_report(), to_date="2025-03-31", filed_cells={"B1": 1},
                              lines=[BalanceSheetLine("Missing", "B1", ("unknown",))])
    with pytest.raises(ValueError, match="as-of date"):
        compare_balance_sheet(_report(), to_date="2024-03-31", filed_cells={}, lines=[])
