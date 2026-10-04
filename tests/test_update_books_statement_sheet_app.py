import json
from decimal import Decimal
from unittest.mock import Mock

import pytest
import yaml

from apps import update_books_statement_sheet as app
from workflows.books_pnl_notes import NOTE_INPUTS, NOTE_SHEET


def test_pnl_only_preview_uses_saved_mapping_without_catalog(monkeypatch, tmp_path, capsys):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps({
        "spreadsheet_id": "sheet", "location_ids": ["location"], "mappings": [],
        "pnl_notes": {"sheet": NOTE_SHEET, "excluded_location_id": "excluded",
                      "partner_interest_cell": "'Note 1 to 3'!G17",
                      "current_start": "2025-04-01", "current_end": "2026-03-31",
                      "account_groups": {"G6": ["sales"]}},
    }), encoding="utf-8")
    monkeypatch.setattr(app, "get_books_client", lambda: "books")
    monkeypatch.setattr(app, "sync_account_catalog", Mock(side_effect=AssertionError("catalog ran")))
    prepare = Mock(return_value={f"'{NOTE_SHEET}'!{cell}": Decimal("0") for cell in NOTE_INPUTS})
    monkeypatch.setattr(app, "prepare_pnl_note_updates", prepare)

    assert app.main([str(path), "--pnl-only", "--partner-interest", "10"]) == 0
    assert "'Notes to P & L 19 to 25'!G15" in capsys.readouterr().out
    assert prepare.call_args.kwargs["partner_interest"] == Decimal("10")
    assert prepare.call_args.kwargs["account_groups"] == {"G6": ["sales"]}


def test_main_uses_dedicated_default_mapping(monkeypatch, tmp_path, capsys):
    mapping_path = tmp_path / "accounting-mapping.yaml"
    mapping_path.write_text(yaml.safe_dump({
        "spreadsheet_id": "sheet-from-yaml",
        "location_ids": ["location-1", "location-2"],
        "mappings": [{
            "report": "profitandloss",
            "source_path": ["amount"],
            "sheet": "Notes",
            "current_cell": "G6",
            "previous_cell": "E6",
        }],
    }), encoding="utf-8")
    books = Mock()
    books.request.side_effect = lambda _method, _endpoint, params: {
        "code": 0,
        "page_context": {
            "from_date": params["from_date"],
            "to_date": params["to_date"],
            "cash_based": "false",
            "filter_by": "TransactionDate.CustomDate",
        },
        "amount": "123.45",
    }
    monkeypatch.setattr(app, "DEFAULT_MAPPING", mapping_path)
    monkeypatch.setattr(app, "DEFAULT_ACCOUNT_DB", tmp_path / "accounts.sqlite3")
    books.chart_of_accounts.list_all.side_effect = [[{
        "account_id": "unused",
        "account_name": "Unused Account",
    }], []]
    monkeypatch.setattr(app, "get_books_client", lambda: books)

    assert app.main([]) == 0

    preview = capsys.readouterr().out
    assert "'Notes'!G6" in preview
    assert "'Notes'!E6" in preview
    assert books.request.call_count == 3
    assert all(
        call.kwargs["params"]["location_ids"] == "location-1,location-2"
        for call in books.request.call_args_list
    )
    assert all(
        call.kwargs["params"]["filter_by"] == "TransactionDate.CustomDate"
        for call in books.request.call_args_list
    )


def test_equity_only_previews_and_applies_without_touching_other_mappings(monkeypatch, tmp_path, capsys):
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({
        "spreadsheet_id": "sheet-id", "location_ids": ["location"],
        "mappings": [{"report": "balancesheet", "account_ids": ["other"],
                      "sheet": "Other", "current_cell": "A1", "previous_cell": "B1"}],
        "equity": {"excluded_location_id": "excluded", "interest_account_id": "interest",
                   "withdrawal_transaction_types": ["transfer_fund"], "movement_header_cell": "I12",
                   "movement_header": "Net movement (unclassified)", "mappings": [
            {"account_id": "owner", "sheet": "Note 1 to 3", "name_cell": "B13",
             "opening_cell": "D13", "interest_cell": "G13", "withdrawal_cell": "H13",
             "movement_cell": "I13", "closing_cell": "J13"},
        ]},
    }), encoding="utf-8")
    monkeypatch.setattr(app, "sync_account_catalog", lambda *_args, **_kwargs: {"owner": "Owner A", "other": "Other"})
    monkeypatch.setattr(app, "prepare_updates", Mock(side_effect=AssertionError("normal mappings ran")))
    monkeypatch.setattr(app, "prepare_equity_updates", lambda *_args, **_kwargs: {
        "'Note 1 to 3'!B13": "Owner A",
        "'Note 1 to 3'!D13": Decimal("100"),
        "'Note 1 to 3'!G13": Decimal("5"),
        "'Note 1 to 3'!H13": Decimal("20"),
        "'Note 1 to 3'!I13": Decimal("-15"),
    })
    monkeypatch.setattr(app, "get_books_client", Mock())

    assert app.main([str(mapping_path), "--equity-only"]) == 0
    assert "Owner A" in capsys.readouterr().out

    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "test-token")
    get_response = Mock()
    get_response.json.return_value = {"valueRanges": [
        {"range": "'Note 1 to 3'!I12", "values": [["Old heading"]]},
        {"range": "'Note 1 to 3'!B13", "values": [["Owner A"]]},
        {"range": "'Note 1 to 3'!D13", "values": [[100]]},
        {"range": "'Note 1 to 3'!G13", "values": [[0]]},
        {"range": "'Note 1 to 3'!H13", "values": [[0]]},
        {"range": "'Note 1 to 3'!I13", "values": [[-15]]},
        {"range": "'Note 1 to 3'!J13", "values": [["=D13+I13"]]},
    ]}
    post_response = Mock()
    post_response.json.return_value = {"totalUpdatedCells": 6}
    monkeypatch.setattr(app.requests, "get", Mock(return_value=get_response))
    monkeypatch.setattr(app.requests, "post", Mock(return_value=post_response))

    assert app.main([str(mapping_path), "--equity-only", "--apply"]) == 0
    payload = app.requests.post.call_args.kwargs["json"]
    assert {entry["range"]: entry["values"][0][0] for entry in payload["data"]} == {
        "'Note 1 to 3'!B13": "Owner A",
        "'Note 1 to 3'!D13": 100.0,
        "'Note 1 to 3'!G13": 5.0,
        "'Note 1 to 3'!H13": 20.0,
        "'Note 1 to 3'!I13": -15.0,
        "'Note 1 to 3'!I12": "Net movement (unclassified)",
    }


def test_equity_apply_requires_closing_formula(monkeypatch, tmp_path):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps({
        "spreadsheet_id": "sheet", "location_ids": ["location"], "mappings": [],
        "equity": {"excluded_location_id": "excluded", "interest_account_id": "interest",
                   "withdrawal_transaction_types": ["transfer_fund"], "movement_header_cell": "I12",
                   "movement_header": "Net movement (unclassified)", "mappings": [
            {"account_id": "owner", "sheet": "Note", "name_cell": "B13",
             "opening_cell": "D13", "interest_cell": "G13", "withdrawal_cell": "H13",
             "movement_cell": "I13", "closing_cell": "J13"},
        ]},
    }), encoding="utf-8")
    monkeypatch.setattr(app, "sync_account_catalog", lambda *_args, **_kwargs: {"owner": "Owner"})
    monkeypatch.setattr(app, "prepare_equity_updates", lambda *_args, **_kwargs: {"'Note'!D13": Decimal("10")})
    monkeypatch.setattr(app, "get_books_client", Mock())
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "test-token")
    response = Mock()
    response.json.return_value = {"valueRanges": [
        {"range": "'Note'!D13", "values": [[0]]},
        {"range": "'Note'!I12", "values": [["Old heading"]]},
        {"range": "'Note'!J13", "values": [[0]]},
    ]}
    monkeypatch.setattr(app.requests, "get", Mock(return_value=response))
    monkeypatch.setattr(app.requests, "post", Mock())

    with pytest.raises(ValueError, match="Expected closing-balance formula"):
        app.main([str(path), "--equity-only", "--apply"])
    app.requests.post.assert_not_called()


@pytest.mark.parametrize("content", ["mappings: [", "- invalid-root"])
def test_invalid_yaml_fails_before_api_access(monkeypatch, tmp_path, content):
    path = tmp_path / "mapping.yaml"
    path.write_text(content, encoding="utf-8")
    client = Mock()
    monkeypatch.setattr(app, "get_books_client", client)
    with pytest.raises(SystemExit):
        app.main([str(path)])
    client.assert_not_called()


def test_default_mapping_path():
    assert app.DEFAULT_MAPPING == app.PROJECT_ROOT / "config" / "accounting-mapping.yaml"
