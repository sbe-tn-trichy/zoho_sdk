from unittest.mock import Mock

import pytest

from zoho.helpers import fetch_equity_general_ledger


def _client():
    books = Mock()
    books.locations.list_all.return_value = [
        {"location_id": "excluded", "location_name": "SBE"},
        {"location_id": "included", "location_name": "B&L"},
    ]
    books.chart_of_accounts.list_all.side_effect = [
        [
            {"account_id": "parent", "account_name": "Owner's Equity", "account_type": "equity"},
            {"account_id": "owner", "account_name": "Owner A", "account_type": "equity"},
            {"account_id": "income", "account_name": "Sales", "account_type": "income"},
        ],
        [{"account_id": "old", "account_name": "Old Equity", "account_type": "equity"}],
    ]

    books.registers.iter_transactions_for_accounts.return_value = iter([
        {"transaction_id": "parent-tx", "account_id": "parent", "branch": {"location_name": "B&L"}},
        {"transaction_id": "owner-tx", "account_id": "owner", "branch": {"location_name": "B&L"}},
        {"transaction_id": "excluded-tx", "account_id": "owner", "branch": {"location_name": "SBE"}},
        {"transaction_id": "old-tx", "account_id": "old", "branch": {"location_name": "B&L"}},
    ])
    return books


def test_fetches_all_equity_accounts_via_sdk_and_excludes_location():
    books = _client()
    entries = fetch_equity_general_ledger(
        books, from_date="2025-04-01", to_date="2026-03-31",
        excluded_location_id="excluded", per_page=500,
    )

    assert [entry["transaction"]["transaction_id"] for entry in entries] == [
        "parent-tx", "owner-tx", "old-tx",
    ]
    assert [entry["account_name"] for entry in entries] == [
        "Owner's Equity", "Owner A", "Old Equity",
    ]
    books.registers.iter_transactions_for_accounts.assert_called_once()
    assert books.registers.iter_transactions_for_accounts.call_args.args[0] == ("parent", "owner", "old")
    assert books.registers.iter_transactions_for_accounts.call_args.kwargs == {
        "from_date": "2025-04-01", "to_date": "2026-03-31",
        "per_page": 500, "cash_based": False,
    }
    assert [call.kwargs["params"]["filter_by"] for call in books.chart_of_accounts.list_all.call_args_list] == [
        "AccountType.Active", "AccountType.Inactive",
    ]


@pytest.mark.parametrize("kwargs, message", [
    ({"from_date": "invalid"}, "ISO dates"),
    ({"from_date": "2026-04-01"}, "after to_date"),
    ({"excluded_location_id": ""}, "excluded_location_id"),
    ({"per_page": 0}, "per_page"),
])
def test_invalid_inputs_fail_before_fetch(kwargs, message):
    books = _client()
    args = {"from_date": "2025-04-01", "to_date": "2026-03-31", "excluded_location_id": "excluded"}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        fetch_equity_general_ledger(books, **args)
    books.locations.list_all.assert_not_called()


def test_ambiguous_location_name_fails_closed():
    books = _client()
    books.locations.list_all.return_value.append({"location_id": "other", "location_name": "SBE"})
    with pytest.raises(ValueError, match="ambiguous"):
        fetch_equity_general_ledger(
            books, from_date="2025-04-01", to_date="2026-03-31",
            excluded_location_id="excluded",
        )
    books.registers.iter_transactions_for_accounts.assert_not_called()


def test_missing_branch_fails_closed():
    books = _client()
    books.registers.iter_transactions_for_accounts.return_value = iter([
        {"transaction_id": "tx", "account_id": "parent"},
    ])
    with pytest.raises(ValueError, match="branch"):
        fetch_equity_general_ledger(
            books, from_date="2025-04-01", to_date="2026-03-31",
            excluded_location_id="excluded",
        )
