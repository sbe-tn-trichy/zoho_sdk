from decimal import Decimal
from unittest.mock import Mock

import pytest

from workflows.books_pnl_notes import NOTE_INPUTS, prepare_pnl_note_updates


def _fixture():
    cells = ("G6", "G15", "G45", "G69", "interest_expense", "G85",
             "G92", "G93", "G95", "G99", "G101", "G102", "G103", "G107")
    mapping = {cell: [cell] for cell in cells}
    sections = {
        "Operating Income": ["G6", "G15", "other-income"],
        "Cost of Goods Sold": ["G45", "other-cogs"],
        "Operating Expense": list(cells[3:]) + ["other-expense"],
        "Non Operating Income": ["non-operating"],
    }
    values = {key: Decimal("1") for ids in sections.values() for key in ids}
    values.update({"G6": Decimal("100"), "G15": Decimal("0"),
                   "other-income": Decimal("5"), "G45": Decimal("40"),
                   "other-cogs": Decimal("10"), "interest_expense": Decimal("8"),
                   "non-operating": Decimal("2")})
    response = {"profit_and_loss": [{"account_transactions": [
        {"name": section, "account_transactions": [
            {"account_id": key, "total": str(values[key])} for key in ids
        ]} for section, ids in sections.items()
    ]}]}
    books = Mock()
    books.reports.profit_and_loss_schedule_format.return_value = response
    return books, mapping


def test_pnl_note_mapping_reconciles_with_one_report_call():
    books, mapping = _fixture()
    result = prepare_pnl_note_updates(
        books, from_date="2025-04-01", to_date="2026-03-31",
        excluded_location_id="excluded", account_groups=mapping,
        partner_interest=Decimal("3"),
    )
    assert set(result) == {f"'Notes to P & L 19 to 25'!{cell}" for cell in NOTE_INPUTS}
    assert result["'Notes to P & L 19 to 25'!G9"] == Decimal("5")
    assert result["'Notes to P & L 19 to 25'!G46"] == Decimal("10")
    assert result["'Notes to P & L 19 to 25'!G76"] == Decimal("5")
    assert result["'Notes to P & L 19 to 25'!G79"] == Decimal("3")
    books.reports.profit_and_loss_schedule_format.assert_called_once()


def test_pnl_note_mapping_rejects_missing_account():
    books, mapping = _fixture()
    mapping["G6"] = ["missing"]
    with pytest.raises(ValueError, match="missing mapped IDs"):
        prepare_pnl_note_updates(
            books, from_date="2025-04-01", to_date="2026-03-31",
            excluded_location_id="excluded", account_groups=mapping,
            partner_interest=Decimal("3"),
        )


def test_live_schedule_shape_and_closing_sections():
    books, mapping = _fixture()
    sections = books.reports.profit_and_loss_schedule_format.return_value["profit_and_loss"][0]["account_transactions"]
    by_name = {section["name"]: section["account_transactions"] for section in sections}
    operating = by_name["Operating Expense"]
    operating.append({**operating[0], "section": True})
    books.reports.profit_and_loss_schedule_format.return_value = {"schedule_profit_and_loss": [
        {"name": "I. Revenue from operations", "account_transactions": by_name["Operating Income"]},
        {"name": "II. Other Income", "account_transactions": by_name["Non Operating Income"]},
        {"name": "IV. Expenses", "account_transactions": [
            {"name": "2. Purchases of stock in trade", "account_transactions": by_name["Cost of Goods Sold"]},
            {"name": "7. Other Expenses", "account_transactions": operating},
        ]},
    ]}
    result = prepare_pnl_note_updates(books, from_date="2025-04-01", to_date="2026-03-31",
        excluded_location_id="excluded", account_groups=mapping, partner_interest=Decimal("3"))
    assert result["'Notes to P & L 19 to 25'!G6"] == Decimal("100")
    assert result["'Notes to P & L 19 to 25'!G46"] == Decimal("10")
