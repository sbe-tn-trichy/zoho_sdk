from decimal import Decimal
from unittest.mock import Mock

import pytest

from workflows.books_statement_sheet import (
    EquityMapping, StatementMapping, StatementPeriod,
    prepare_equity_updates, prepare_updates,
)


PERIODS = StatementPeriod("2025-04-01", "2026-03-31", "2024-04-01", "2025-03-31")


def _report(_method, _endpoint, params):
    return {
        "code": 0,
        "page_context": {"from_date": params["from_date"], "to_date": params["to_date"],
                         "cash_based": "false", "filter_by": "TransactionDate.CustomDate"},
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
    assert all(
        call.kwargs["params"]["filter_by"] == "TransactionDate.CustomDate"
        for call in books.request.call_args_list
    )


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


EQUITY = EquityMapping("owner", "Note 1 to 3", "B13", "D13", "G13", "H13", "I13", "J13")


def _equity_report(_method, _endpoint, params):
    amount = "85" if params["from_date"] == "2025-04-01" else "100"
    return {
        "code": 0,
        "page_context": {"to_date": params["to_date"],
                         "filter_by": "TransactionDate.CustomDate", "cash_based": "false"},
        "balance_sheet": [{"account_transactions": [
            {"account_id": "owner", "total": amount},
        ]}],
    }


def test_equity_updates_reconcile_ledger_and_leave_closing_formula(monkeypatch):
    books = Mock()
    books.request.side_effect = _equity_report
    ledger = Mock(return_value=[
        {"account_id": "owner", "transaction": {"debit": "0", "credit": "5", "offset_account_id": "interest"}},
        {"account_id": "owner", "transaction": {"debit": "20", "credit": "0", "transaction_type": "transfer_fund"}},
    ])
    monkeypatch.setattr("workflows.books_statement_sheet.fetch_equity_general_ledger", ledger)

    updates = prepare_equity_updates(
        books, PERIODS, [EQUITY], location_ids=["location"],
        excluded_location_id="excluded", account_names={"owner": "Owner A"},
        interest_account_id="interest", withdrawal_transaction_types=("transfer_fund", "owner_drawings"),
    )

    assert updates == {
        "'Note 1 to 3'!B13": "Owner A",
        "'Note 1 to 3'!D13": Decimal("100"),
        "'Note 1 to 3'!G13": Decimal("5"),
        "'Note 1 to 3'!H13": Decimal("20"),
        "'Note 1 to 3'!I13": Decimal("0"),
    }
    ledger.assert_called_once_with(
        books, from_date="2025-04-01", to_date="2026-03-31",
        excluded_location_id="excluded",
    )
    assert all(call.kwargs["params"]["location_ids"] == "location" for call in books.request.call_args_list)


def test_equity_reconciliation_rejects_mismatch(monkeypatch):
    books = Mock()
    books.request.side_effect = _equity_report
    monkeypatch.setattr("workflows.books_statement_sheet.fetch_equity_general_ledger", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="does not reconcile"):
        prepare_equity_updates(
            books, PERIODS, [EQUITY], location_ids=["location"],
            excluded_location_id="excluded", account_names={"owner": "Owner A"},
            interest_account_id="interest", withdrawal_transaction_types=("transfer_fund",),
        )


def test_equity_rejects_invalid_ledger_amount(monkeypatch):
    books = Mock()
    books.request.side_effect = _equity_report
    monkeypatch.setattr("workflows.books_statement_sheet.fetch_equity_general_ledger", lambda *_args, **_kwargs: [
        {"account_id": "owner", "transaction": {"debit": "NaN", "credit": "5"}},
    ])
    with pytest.raises(ValueError, match="invalid debit"):
        prepare_equity_updates(
            books, PERIODS, [EQUITY], location_ids=["location"],
            excluded_location_id="excluded", account_names={"owner": "Owner A"},
            interest_account_id="interest", withdrawal_transaction_types=("transfer_fund",),
        )
