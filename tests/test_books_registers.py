from unittest.mock import Mock

import pytest

from zoho.books.resources.ledger import Registers


def test_register_request_uses_custom_dates_and_keeps_raw_response():
    client = Mock()
    response = {
        "code": 0,
        "register_transactions": {"account_transactions": []},
        "page_context": {"has_more_page": False},
    }
    client.request.return_value = response

    result = Registers(client).list_transactions(
        "account-1", from_date="2025-04-01", to_date="2026-03-31", page=2,
        per_page=500,
    )

    assert result is response
    client.request.assert_called_once_with(
        "GET", "registers/account-1/transactions",
        params={
            "account_id": "account-1",
            "filter_by": "TransactionDate.CustomDate",
            "from_date": "2025-04-01", "to_date": "2026-03-31",
            "cash_based": "false", "page": 2, "per_page": 500,
        },
    )


def test_register_iterator_flattens_grouped_rows_across_pages():
    client = Mock()
    client.request.side_effect = [
        {"code": 0, "register_transactions": {"account_transactions": [
            {"account_transactions": [{"transaction_id": "one", "debit_amount": 10}]},
        ]}, "page_context": {"has_more_page": True}},
        {"code": 0, "register_transactions": {"account_transactions": [
            {"account_transactions": [{"transaction_id": "two", "credit_amount": 5}]},
        ]}, "page_context": {"has_more_page": False}},
    ]

    rows = list(Registers(client).iter_transactions(
        "account-1", from_date="2025-04-01", to_date="2026-03-31",
    ))

    assert [row["transaction_id"] for row in rows] == ["one", "two"]
    assert [call.kwargs["params"]["page"] for call in client.request.call_args_list] == [1, 2]


def test_batch_account_filter_uses_one_query_with_comma_separated_ids():
    client = Mock()
    client.request.return_value = {
        "code": 0,
        "register_transactions": {"account_transactions": [{"account_transactions": [
            {"transaction_id": "one", "account_id": "a"},
            {"transaction_id": "two", "account_id": "b"},
        ]}]},
        "page_context": {"has_more_page": False},
    }

    rows = list(Registers(client).iter_transactions_for_accounts(
        ["a", "b"], from_date="2025-04-01", to_date="2026-03-31",
    ))

    assert len(rows) == 2
    client.request.assert_called_once()
    assert client.request.call_args.args[1] == "registers/a/transactions"
    assert client.request.call_args.kwargs["params"]["account_id"] == "a,b"


def test_batch_account_filter_rejects_string_and_duplicates():
    resource = Registers(Mock())
    for account_ids in ("a,b", ["a", "a"]):
        with pytest.raises(ValueError):
            resource.list_transactions_for_accounts(
                account_ids, from_date="2025-04-01", to_date="2026-03-31",
            )


@pytest.mark.parametrize("kwargs, message", [
    ({"account_id": ""}, "account_id"),
    ({"from_date": "2025-99-01"}, "ISO dates"),
    ({"from_date": "2026-04-01"}, "after to_date"),
    ({"page": 0}, "positive"),
])
def test_register_rejects_invalid_inputs_before_request(kwargs, message):
    client = Mock()
    args = {"account_id": "account-1", "from_date": "2025-04-01", "to_date": "2026-03-31"}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        Registers(client).list_transactions(**args)
    client.request.assert_not_called()


def test_register_rejects_failed_and_malformed_responses():
    client = Mock()
    resource = Registers(client)
    for response in ({"code": 5}, {"code": 0}, {"code": 0, "register_transactions": {}}):
        client.request.return_value = response
        with pytest.raises(ValueError):
            list(resource.iter_transactions(
                "account-1", from_date="2025-04-01", to_date="2026-03-31",
            ))
