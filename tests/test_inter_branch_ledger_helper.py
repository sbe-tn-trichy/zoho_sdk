from unittest.mock import Mock

import pytest

import json

from zoho.helpers import fetch_inter_branch_general_ledger, fetch_inter_branch_register_transactions


def _books():
    books = Mock()
    books.locations.list_all.return_value = [
        {"location_id": "excluded", "location_name": "SBE"},
        {"location_id": "included", "location_name": "BD"},
    ]
    books.registers.iter_transactions.return_value = iter([
        {"transaction_id": "one", "account_id": "inter", "branch": {"location_name": "BD"}},
        {"transaction_id": "two", "account_id": "inter", "branch": {"location_name": "SBE"}},
    ])
    return books


def test_fetches_filtered_general_ledger_balance():
    books = _books()
    books.reports.general_ledger.return_value = {"generalledger": [{
        "account_id": "inter", "debit_total": 14945, "credit_total": 63120,
        "balance": 48175, "is_debit": False,
    }]}
    result = fetch_inter_branch_general_ledger(
        books, from_date="2025-04-01", to_date="2026-03-31",
        account_id="inter", excluded_location_id="excluded",
    )
    assert result.balance == 48175
    assert result.is_debit is False
    kwargs = books.reports.general_ledger.call_args.kwargs
    assert kwargs["cash_based"] is False
    assert json.loads(kwargs["rule"]) == {"columns": [
        {"index": 1, "field": "account_id", "value": ["inter"], "comparator": "in", "group": "report"},
        {"index": 2, "field": "location_name", "value": ["excluded"], "comparator": "not_in", "group": "branch"},
    ], "criteria_string": "( 1 AND 2 )"}


def test_raw_register_helper_excludes_sbe():
    books = _books()
    entries = fetch_inter_branch_register_transactions(
        books, from_date="2025-04-01", to_date="2026-03-31",
        account_id="inter", excluded_location_id="excluded",
    )
    assert [entry["transaction"]["transaction_id"] for entry in entries] == ["one"]
    books.registers.iter_transactions.assert_called_once_with(
        "inter", from_date="2025-04-01", to_date="2026-03-31",
        per_page=500, cash_based=False,
    )


@pytest.mark.parametrize("changes, error", [
    ({"from_date": "bad"}, "ISO dates"),
    ({"to_date": "2024-03-31"}, "after to_date"),
    ({"account_id": ""}, "account_id"),
    ({"excluded_location_id": ""}, "excluded_location_id"),
])
def test_invalid_arguments_fail_before_sdk_call(changes, error):
    books = _books()
    arguments = {"from_date": "2025-04-01", "to_date": "2026-03-31",
                 "account_id": "inter", "excluded_location_id": "excluded"}
    arguments.update(changes)
    with pytest.raises(ValueError, match=error):
        fetch_inter_branch_general_ledger(books, **arguments)
    books.reports.general_ledger.assert_not_called()


def test_unexpected_account_or_missing_branch_fails():
    books = _books()
    books.registers.iter_transactions.return_value = iter([
        {"account_id": "other", "branch": {"location_name": "BD"}},
    ])
    with pytest.raises(ValueError, match="unexpected account"):
        fetch_inter_branch_register_transactions(books, from_date="2025-04-01", to_date="2026-03-31",
                                          account_id="inter", excluded_location_id="excluded")
    books.registers.iter_transactions.return_value = iter([{"account_id": "inter"}])
    with pytest.raises(ValueError, match="branch details"):
        fetch_inter_branch_register_transactions(books, from_date="2025-04-01", to_date="2026-03-31",
                                          account_id="inter", excluded_location_id="excluded")
