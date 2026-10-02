"""Mock-based request and pagination tests; payload shape is illustrative."""
import json
from unittest.mock import Mock

import pytest

from zoho.books.resources.reports import Reports


ARGS = {"account_ids": ["a", "b"], "from_date": "2025-04-01", "to_date": "2026-03-31"}


def response(page=1, more=False, payload=None):
    return {"code": 0, "message": "success", "report_payload": payload or [page],
            "page_context": {"page": page, "has_more_page": more}}


def test_request_preserves_response_and_encodes_account_filter():
    client = Mock()
    client.request.return_value = response()
    result = Reports(client).general_ledger_details(**ARGS)
    assert result is client.request.return_value
    client.request.assert_called_once()
    call = client.request.call_args
    assert call.args == ("GET", "reports/generalledgerdetails")
    params = call.kwargs["params"]
    assert params["per_page"] == 500
    assert params["page"] == 1
    assert params["filter_by"] == "TransactionDate.CustomDate"
    assert params["from_date"] == ARGS["from_date"]
    assert params["to_date"] == ARGS["to_date"]
    assert params["cash_based"] == "false"
    rule = json.loads(params["rule"])
    assert rule["columns"][0]["value"] == ["a", "b"]
    assert rule["columns"][0]["comparator"] == "in"
    assert json.loads(params["group_by"]) == [{"field": "account_name", "group": "report"}]
    assert "transaction_details" in [c["field"] for c in json.loads(params["select_columns"])]


@pytest.mark.parametrize("overrides", [
    {"account_ids": "a"}, {"account_ids": []}, {"account_ids": ["a", "a"]},
    {"account_ids": [None]}, {"from_date": "invalid"},
    {"from_date": "2027-01-01"}, {"page": 0}, {"page": True},
    {"per_page": 501}, {"per_page": 0}, {"cash_based": "false"},
])
def test_invalid_inputs_do_not_request(overrides):
    client = Mock()
    with pytest.raises(ValueError):
        Reports(client).general_ledger_details(**(ARGS | overrides))
    client.request.assert_not_called()


@pytest.mark.parametrize("payload", [
    None, {"code": 5}, {"code": 0},
    {"code": 0, "page_context": {"has_more_page": "false"}}, response(page=2),
])
def test_rejects_failed_or_invalid_response(payload):
    client = Mock()
    client.request.return_value = payload
    with pytest.raises(ValueError):
        Reports(client).general_ledger_details(**ARGS)


def test_pagination_stops_at_last_page():
    client = Mock()
    client.request.side_effect = [response(more=True), response(page=2)]
    pages = list(Reports(client).iter_general_ledger_details_pages(**ARGS))
    assert len(pages) == 2
    assert [call.kwargs["params"]["page"] for call in client.request.call_args_list] == [1, 2]


def test_repeated_content_stops_before_yielding_duplicates():
    client = Mock()
    client.request.side_effect = [response(more=True), response(page=2, more=True, payload=[1])]
    pages = Reports(client).iter_general_ledger_details_pages(**ARGS)
    next(pages)
    with pytest.raises(ValueError, match="repeated"):
        next(pages)
    assert client.request.call_count == 2


def test_request_bound_raises_instead_of_returning_partial_report():
    client = Mock()
    client.request.return_value = response(more=True)
    with pytest.raises(ValueError, match="max_pages"):
        list(Reports(client).iter_general_ledger_details_pages(**ARGS, max_pages=1))
    client.request.assert_called_once()
    client.reset_mock()
    with pytest.raises(ValueError, match="positive"):
        list(Reports(client).iter_general_ledger_details_pages(**ARGS, max_pages=0))
    client.request.assert_not_called()
