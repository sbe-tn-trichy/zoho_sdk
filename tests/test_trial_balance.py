import json
from unittest.mock import Mock

import pytest

from zoho.books.resources.reports import Reports
from workflows import fetch_trial_balance_for_firm, fetch_trial_balance_for_gstin
from workflows.audited_financials import reports as helpers


ARGS = {"from_date": "2024-04-01", "to_date": "2025-03-31"}
RULE = {"columns": [{"index": 1, "field": "location_name",
    "value": ["1094368000044509446"], "comparator": "not_in", "group": "branch"}],
    "criteria_string": "1"}


@pytest.fixture(autouse=True)
def firm_config(tmp_path, monkeypatch):
    config = {"default_firm": "BD", "firms": {
        "BD": {"name": "Bharath Distributors", "gstin": "33AATFB2164K1Z9", "aliases": [],
               "scope": {"comparator": "not_in", "location_ids": ["1094368000044509446"]}},
        "SBE": {"name": "Sri Bharath Electricals", "gstin": "33AFSFS0069L1ZH", "aliases": [],
                "scope": {"comparator": "in", "location_ids": ["1094368000044509446"]}},
    }}
    path = tmp_path / "firms.yaml"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(helpers, "get_config", lambda key, default: str(path))
    return path, config


def client_response():
    client = Mock()
    client.reports = Reports(client)
    client.request.return_value = {"code": 0, "trial_balance": [{"name": "Cash"}],
        "page_context": {**ARGS, "cash_based": "false", "rule": RULE}}
    return client


def test_gstin_helper_preserves_payload_and_scopes_sdk_request():
    client = client_response()
    result = fetch_trial_balance_for_gstin(client, **ARGS)
    assert result is client.request.return_value
    method, endpoint = client.request.call_args.args
    params = client.request.call_args.kwargs["params"]
    assert (method, endpoint) == ("GET", "reports/trialbalance")
    assert json.loads(params["rule"]) == RULE
    assert params["cash_based"] == "false"
    assert params["show_rows"] == "non_zero"
    assert params["amount_format"] == "dr_cr"
    assert [column["field"] for column in json.loads(params["select_columns"])] == [
        "name", "opening_balance", "net_debit", "net_credit", "closing_balance"]


@pytest.mark.parametrize("overrides", [
    {"from_date": "bad"}, {"from_date": "2026-01-01"},
    {"cash_based": "false"}, {"show_rows": "invalid"},
    {"rule": "not json"}, {"rule": "[]"}, {"rule": '{"columns": [1]}'},
])
def test_invalid_arguments_fail_before_request(overrides):
    client = client_response()
    with pytest.raises(ValueError):
        client.reports.trial_balance(**(ARGS | overrides))
    client.request.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("from_date", "2025-04-01"), ("to_date", "2026-03-31"),
    ("cash_based", "true"), ("rule", {}),
])
def test_ignored_report_filters_rejected(field, value):
    client = client_response()
    client.request.return_value["page_context"][field] = value
    with pytest.raises(ValueError):
        fetch_trial_balance_for_gstin(client, **ARGS)


def test_failure_and_unreviewed_gstin():
    client = client_response()
    with pytest.raises(ValueError, match="reviewed GSTIN"):
        fetch_trial_balance_for_gstin(client, **ARGS, gstin="another")
    client.request.assert_not_called()
    client.request.return_value = {"code": 57}
    with pytest.raises(ValueError, match="request failed"):
        client.reports.trial_balance(**ARGS)


def test_unfiltered_all_rows_supported():
    client = client_response()
    client.reports.trial_balance(**ARGS, show_rows="all")
    params = client.request.call_args.kwargs["params"]
    assert "rule" not in params
    assert params["show_rows"] == "all"


@pytest.mark.parametrize("firm,comparator", [
    ("BD", "not_in"), ("Bharath Distributors", "not_in"),
    ("  bharath   DISTRIBUTORS  ", "not_in"), ("33AATFB2164K1Z9", "not_in"),
    ("SBE", "in"), ("Sri Bharath Electricals", "in"),
    (" sri BHARATH electricals ", "in"), ("33AFSFS0069L1ZH", "in"),
])
def test_firm_aliases_apply_the_correct_location_scope(firm, comparator):
    client = client_response()
    applied = json.loads(json.dumps(RULE))
    applied["columns"][0]["comparator"] = comparator
    client.request.return_value["page_context"]["rule"] = applied
    fetch_trial_balance_for_firm(client, **ARGS, firm=firm)
    assert json.loads(client.request.call_args.kwargs["params"]["rule"]) == applied


@pytest.mark.parametrize("firm", ["", "unknown", 123])
def test_unknown_firm_fails_without_network(firm):
    client = client_response()
    with pytest.raises(ValueError, match="Unknown firm"):
        fetch_trial_balance_for_firm(client, **ARGS, firm=firm)
    client.request.assert_not_called()


def test_config_controls_identity_scope_and_default(firm_config):
    path, config = firm_config
    config["default_firm"] = "NEW"
    config["firms"] = {"NEW": {"name": "New Company", "gstin": "NEW-GSTIN", "aliases": ["NC"],
        "scope": {"comparator": "in", "location_ids": ["new-location"]}}}
    path.write_text(json.dumps(config), encoding="utf-8")
    client = Mock()
    for selector in (None, "New Company", "NEW-GSTIN", " nc "):
        fetch_trial_balance_for_firm(client, **ARGS, firm=selector, config_path=path)
        rule = json.loads(client.reports.trial_balance.call_args.kwargs["rule"])
        assert rule["columns"][0]["value"] == ["new-location"]
        assert rule["columns"][0]["comparator"] == "in"


@pytest.mark.parametrize("change", ["duplicate_alias", "bad_scope", "empty_locations", "no_default"])
def test_bad_firm_config_fails_before_request(firm_config, change):
    path, config = firm_config
    if change == "duplicate_alias":
        config["firms"]["SBE"]["aliases"] = ["BD"]
    elif change == "bad_scope":
        config["firms"]["BD"]["scope"]["comparator"] = "equals"
    elif change == "empty_locations":
        config["firms"]["BD"]["scope"]["location_ids"] = []
    else:
        del config["default_firm"]
    path.write_text(json.dumps(config), encoding="utf-8")
    client = Mock()
    with pytest.raises(ValueError):
        fetch_trial_balance_for_firm(client, **ARGS, config_path=path)
    client.reports.trial_balance.assert_not_called()
