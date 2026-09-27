import json

import pytest

from zoho.books.resources.reports import Reports
from zoho.helpers import fetch_profit_and_loss_schedule_format


class FakeClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = {"code": 0, "profit_and_loss": [], "page_context": {
            "from_date": "2025-04-01", "to_date": "2026-03-31",
            "cash_based": "false", "filter_by": "TransactionDate.CustomDate",
            "rule": {"criteria_string": "1", "columns": [{
                "index": 1, "field": "location_name",
                "value": ["1094368000044509446"], "comparator": "not_in",
                "group": "branch",
            }]},
        }} if response is None else response

    def request(self, method, endpoint, *, params):
        self.calls.append((method, endpoint, params))
        return self.response


def test_schedule_format_helper_wraps_sdk_request():
    client = FakeClient()
    client.reports = Reports(client)

    result = fetch_profit_and_loss_schedule_format(
        client, from_date="2025-04-01", to_date="2026-03-31",
        excluded_location_id="1094368000044509446",
    )

    assert result is client.response
    method, endpoint, params = client.calls[0]
    assert (method, endpoint) == ("GET", "reports/profitandloss")
    assert params["from_date"] == "2025-04-01"
    assert params["to_date"] == "2026-03-31"
    assert params["cash_based"] == "false"
    assert params["filter_by"] == "TransactionDate.CustomDate"
    assert params["show_rows"] == "all"
    assert params["is_expand"] == "true"
    assert json.loads(params["rule"]) == {
        "columns": [{"index": 1, "field": "location_name",
                     "value": ["1094368000044509446"], "comparator": "not_in",
                     "group": "branch"}],
        "criteria_string": "1",
    }


@pytest.mark.parametrize("start,end", [("bad", "2026-03-31"), ("2026-04-01", "2026-03-31")])
def test_schedule_format_rejects_bad_dates(start, end):
    client = FakeClient()
    with pytest.raises(ValueError):
        Reports(client).profit_and_loss_schedule_format(from_date=start, to_date=end, rule="{}")
    assert client.calls == []


def test_schedule_format_rejects_api_failure():
    client = FakeClient({"code": 5, "message": "not found"})
    with pytest.raises(ValueError, match="request failed"):
        Reports(client).profit_and_loss_schedule_format(
            from_date="2025-04-01", to_date="2026-03-31", rule="{}")


def test_helper_requires_excluded_location():
    client = FakeClient()
    with pytest.raises(ValueError, match="excluded_location_id"):
        fetch_profit_and_loss_schedule_format(
            client, from_date="2025-04-01", to_date="2026-03-31",
            excluded_location_id="")


def test_schedule_format_rejects_ignored_rule():
    client = FakeClient({"code": 0, "profit_and_loss": [], "page_context": {
        "from_date": "2025-04-01", "to_date": "2026-03-31",
        "cash_based": "false", "filter_by": "TransactionDate.CustomDate",
    }})
    with pytest.raises(ValueError, match="branch rule"):
        Reports(client).profit_and_loss_schedule_format(
            from_date="2025-04-01", to_date="2026-03-31", rule="{}")
