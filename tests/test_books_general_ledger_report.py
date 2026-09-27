import json
from unittest.mock import Mock

import pytest

from zoho.books.resources.reports import Reports


RULE = {"columns": [{"index": 1, "field": "account_id", "value": ["inter"],
                    "comparator": "in", "group": "report"}], "criteria_string": "1"}


def _response():
    return {"code": 0, "generalledger": [{"account_id": "inter", "balance": 5}],
            "page_context": {"from_date": "2025-04-01", "to_date": "2026-03-31",
                             "cash_based": "false", "filter_by": "TransactionDate.CustomDate",
                             "rule": RULE}}


def test_general_ledger_requests_and_verifies_filters():
    client = Mock()
    client.request.return_value = _response()
    result = Reports(client).general_ledger(from_date="2025-04-01", to_date="2026-03-31",
                                            rule=json.dumps(RULE))
    assert result["generalledger"][0]["balance"] == 5
    assert client.request.call_args.args == ("GET", "reports/generalledger")


def test_general_ledger_rejects_ignored_rule():
    client = Mock()
    response = _response()
    response["page_context"]["rule"] = {"columns": [], "criteria_string": ""}
    client.request.return_value = response
    with pytest.raises(ValueError, match="requested rule"):
        Reports(client).general_ledger(from_date="2025-04-01", to_date="2026-03-31",
                                       rule=json.dumps(RULE))
