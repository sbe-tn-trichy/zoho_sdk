from decimal import Decimal
from unittest.mock import Mock

import pytest

from workflows.books_statement_sheet import StatementMapping, StatementPeriod, prepare_updates


PERIODS = StatementPeriod("2025-04-01", "2026-03-31", "2024-04-01", "2025-03-31")


def _report(_method, _endpoint, params):
    return {
        "code": 0,
        "page_context": {"from_date": params["from_date"], "to_date": params["to_date"],
                         "cash_based": "false"},
        "profit_and_loss": [{"account_transactions": [
            {"account_id": "sales-1", "total": "120.25"},
            {"account_id": "sales-2", "total": "79.75"},
        ]}],
    }


def test_fetches_each_report_period_once_and_sums_account_ids():
    books = Mock()
    books.request.side_effect = _report
    mappings = [
        StatementMapping("profitandloss", (), "Notes to P & L 19 to 25", "E6", "G6",
                         account_ids=("sales-1", "sales-2")),
        StatementMapping("profitandloss", (), "Notes to P & L 19 to 25", "E7", "G7",
                         account_ids=("sales-1",)),
    ]
    updates = prepare_updates(books, PERIODS, mappings)
    assert updates["'Notes to P & L 19 to 25'!E6"] == Decimal("200.00")
    assert updates["'Notes to P & L 19 to 25'!G7"] == Decimal("120.25")
    assert books.request.call_count == 2


def test_missing_account_fails_closed():
    books = Mock()
    books.request.side_effect = _report
    mapping = StatementMapping("profitandloss", (), "Notes", "E6", "G6", account_ids=("absent",))
    with pytest.raises(ValueError, match="missing account IDs"):
        prepare_updates(books, PERIODS, [mapping])


def test_duplicate_target_fails_closed():
    books = Mock()
    books.request.side_effect = _report
    mapping = StatementMapping("profitandloss", ("profit_and_loss", "0", "account_transactions", "0", "total"),
                               "Notes", "E6", "G6")
    with pytest.raises(ValueError, match="Duplicate target cell"):
        prepare_updates(books, PERIODS, [mapping, mapping])
