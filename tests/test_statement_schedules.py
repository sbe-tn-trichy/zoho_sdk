from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from workflows.statement_schedules import build_schedule_plan, fetch_schedule_sources, validate_sources, verify_asset
from zoho.books.resources.fixed_assets import FixedAssets
from apps.update_statement_schedules import apply_plan, grid_address, main, update_requests


def asset():
    return {"fixed_asset_id": "asset", "asset_name": "Machine", "location_id": "branch", "location_name": "Branch",
            "asset_purchase_date": "2025-10-01", "depreciation_start_date": "2025-10-01",
            "depreciation_percentage": 15, "depreciation_method": "declining_method",
            "depreciation_frequency": "yearly", "computation_type": "prorata_basis", "salvage_value": 0}


def history():
    return [{"valuation_id": "a", "type": "acquisition", "valuation_date": "2025-10-01", "revise_value": 1000,
             "current_value": 1000, "depreciated_value": 0, "is_journal_posted": False},
            {"valuation_id": "b", "type": "depreciation", "valuation_date": "2026-03-31", "revise_value": -74.79,
             "current_value": 925.21, "depreciated_value": 74.79, "is_journal_posted": True}]


def test_prorata_includes_purchase_day_and_after_september_additions():
    result = verify_asset(asset(), history(), start="2025-04-01", end="2026-03-31")
    assert result.opening == 0
    assert result.before_cutoff == 0
    assert result.after_cutoff == 1000
    assert result.calculated == Decimal("74.79")
    assert result.closing == Decimal("925.21")
    assert result.difference == 0


def test_full_year_method_and_historical_opening_ignore_todays_wdv():
    record = asset() | {"computation_type": "no_prorata", "current_asset_value": 1}
    rows = history()
    rows[1].update(revise_value=-150, depreciated_value=150, current_value=850)
    result = verify_asset(record, rows, start="2026-04-01", end="2027-03-31")
    assert result.opening == 850
    assert result.calculated == Decimal("127.50")
    assert result.posted == 0


@pytest.mark.parametrize("change", [
    {"depreciation_method": "straight_line"}, {"depreciation_frequency": "monthly"},
    {"depreciation_percentage": -1}, {"depreciation_percentage": "NaN"}, {"salvage_value": 10},
])
def test_unsupported_and_invalid_asset_calculations_fail(change):
    with pytest.raises(ValueError):
        verify_asset(asset() | change, history(), start="2025-04-01", end="2026-03-31")


def test_unposted_depreciation_is_not_treated_as_a_posting():
    rows = history()
    rows[1]["is_journal_posted"] = False
    result = verify_asset(asset(), rows, start="2025-04-01", end="2026-03-31")
    assert result.posted == 0
    assert result.closing == 1000


@pytest.mark.parametrize("mutation", ["duplicate", "gap", "disposal", "missing_acquisition"])
def test_bad_history_fails_closed(mutation):
    rows = history()
    if mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "gap":
        rows[1]["current_value"] = 3
    elif mutation == "disposal":
        rows[1]["type"] = "writeoff"
    else:
        rows = rows[1:]
    with pytest.raises(ValueError):
        verify_asset(asset(), rows, start="2025-04-01", end="2026-03-31")


def config_and_sources():
    config = yaml.safe_load((Path(__file__).parents[1] / "config/statement-schedules.example.yaml").read_text())
    config["excluded_location_id"] = "excluded"
    reports = {}
    for period in config["periods"]:
        scope = {"criteria_string": "1", "columns": [{"index": 1, "field": "location_name", "value": ["excluded"],
                  "comparator": "not_in", "group": "branch"}]}
        context = {"from_date": period["start"], "to_date": period["end"], "cash_based": "false",
                   "filter_by": "TransactionDate.CustomDate", "rule": scope}
        def nest(path, total, account=None):
            row = {"name": path[-1], "total": total}
            if account:
                row["account_id"] = account
            for name in reversed(path[:-1]):
                row = {"name": name, "account_transactions": [row]}
            return row
        bs = [{"name": "ASSETS", "total": 100, "account_transactions": []},
              {"name": "EQUITY AND LIABILITIES", "total": 100, "account_transactions": []}]
        for note in config["notes"]:
            if note["report"] == "balancesheet":
                value = 100 if note["number"] in (1, 6) else 0
                row = nest(note["paths"][0][1:] + ["Account" + str(note["number"])], value, "id" + str(note["number"]))
                bs[0 if note["number"] >= 6 else 1]["account_transactions"].append(row)
        pnl = []
        for note in config["notes"]:
            if note["report"] == "profitandloss":
                pnl.append(nest(note["paths"][0] + ["P&L " + str(note["number"])], 0, "id" + str(note["number"])))
        for direct in config["direct_inputs"]:
            if direct["report"] == "balancesheet":
                bs[1]["account_transactions"].append(nest(direct["path"][1:], 0))
            else:
                pnl.append(nest(direct["path"], 0))
        pnl.append(nest(config["checks"]["profit_before_tax_path"], 0))
        reports[period["label"]] = {"balancesheet": {"code": 0, "page_context": deepcopy(context), "schedule_balance_sheet": bs},
                                     "profitandloss": {"code": 0, "page_context": deepcopy(context), "schedule_profit_and_loss": pnl}}
    sources = {"reports": reports, "assets": [], "periods": config["periods"], "excluded_location_id": "excluded",
               "organization_id": config["organization_id"]}
    return config, sources


def test_plan_links_two_year_notes_and_does_not_write_statement_subtotals():
    config, sources = config_and_sources()
    plan = build_schedule_plan(sources, config)
    assert plan.checks["fy2025-26"]["assets"] == "100.00"
    assert plan.values["'Balance Sheet'!C6"][0][0].startswith("='Notes to Accounts'!B")
    assert plan.values["'Balance Sheet'!D6"][0][0].startswith("='Notes to Accounts'!C")
    assert "'Balance Sheet'!C31" not in plan.values
    assert "'Profit and Loss'!C19" not in plan.values


@pytest.mark.parametrize("bad", ["date", "scope", "basis", "duplicate", "unmapped", "total", "target"])
def test_plan_rejects_incomplete_or_ambiguous_sources(bad):
    config, sources = config_and_sources()
    current = sources["reports"]["fy2025-26"]
    if bad == "date":
        current["profitandloss"]["page_context"]["from_date"] = "2000-01-01"
    elif bad == "scope":
        current["balancesheet"]["page_context"]["rule"]["columns"][0]["value"] = ["other"]
    elif bad == "basis":
        current["balancesheet"]["page_context"]["cash_based"] = "true"
    elif bad == "duplicate":
        current["profitandloss"]["schedule_profit_and_loss"].append(deepcopy(current["profitandloss"]["schedule_profit_and_loss"][0]))
    elif bad == "unmapped":
        current["profitandloss"]["schedule_profit_and_loss"].append({"name": "Unknown", "account_id": "new", "total": 10})
    elif bad == "total":
        current["balancesheet"]["schedule_balance_sheet"][0]["total"] = 99
    else:
        config["direct_inputs"][0]["row"] = 6
    with pytest.raises(ValueError):
        build_schedule_plan(sources, config)


def test_only_four_report_calls_and_asset_scope(monkeypatch):
    config, sources = config_and_sources()
    fetch = Mock(side_effect=[sources["reports"][p["label"]] for p in config["periods"]])
    monkeypatch.setattr("workflows.statement_schedules.workflow.fetch_schedule_reports", fetch)
    books = Mock(organization_id="org")
    books.fixed_assets.list_iter.return_value = [{"fixed_asset_id": "skip", "location_id": "excluded"}]
    result = fetch_schedule_sources(books, periods=config["periods"], excluded_location_id="excluded")
    assert fetch.call_count == 2  # Each helper fetches precisely the two report kinds.
    assert result["assets"] == []
    books.fixed_assets.get.assert_not_called()


def test_fixed_asset_history_pagination_and_duplicate_guard():
    books = Mock()
    first, second = history()
    books.request.side_effect = [{"code": 0, "asset_history": [first], "page_context": {"has_more_page": True}},
                                 {"code": 0, "asset_history": [second]}]
    assert FixedAssets(books).history("asset") == history()
    assert books.request.call_args_list[1].kwargs["params"]["page"] == 2
    books.request.side_effect = [{"code": 0, "asset_history": [first, first]}]
    with pytest.raises(ValueError, match="repeated"):
        FixedAssets(books).history("asset")


def test_native_writes_keep_external_text_literal_and_formula_mask_precise():
    config, sources = config_and_sources()
    plan = build_schedule_plan(sources, config)
    note_address = next(a for a in plan.values if a.startswith("'Notes"))
    plan.values[note_address][0][0] = "=IMPORTXML(\"evil\")"
    requests = update_requests(plan.values, config)
    note = next(r["updateCells"] for r in requests if r["updateCells"]["range"]["sheetId"] == config["sheet_ids"]["notes"])
    assert note["rows"][0]["values"][0]["userEnteredValue"] == {"stringValue": "=IMPORTXML(\"evil\")"}
    assert all(r["updateCells"]["fields"] == "userEnteredValue" for r in requests)
    assert grid_address("'O''Reilly'!AA2:AB4") == ("O'Reilly", 1, 26, 4, 28)


def test_offline_cli_writes_preview_without_constructing_books(monkeypatch, tmp_path):
    import json
    config, sources = config_and_sources()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(sources))
    monkeypatch.setattr("apps.update_statement_schedules.get_books_client", Mock(side_effect=AssertionError("network")))
    assert main(["--config", str(config_path), "--saved", str(source_path), "--output", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out/preview.md").is_file()


class SheetsSession:
    def __init__(self, config, *, validation=False, existing_formula=False, corrupt_readback=False):
        self.config = config
        self.validation = validation
        self.existing_formula = existing_formula
        self.corrupt_readback = corrupt_readback
        self.read_count = 0
        self.posted = []
        self.cells = {}

    def response(self, data):
        return Mock(json=lambda: data, raise_for_status=Mock())

    def get(self, url, *, params, **kwargs):
        if "values:batchGet" not in url:
            if params.get("includeGridData"):
                return self.response({"sheets": [{"properties": {"title": title}, "data": [{"rowData": [
                    {"values": [{"dataValidation": {"strict": True}}] if self.validation else []}]}]}
                    for title in self.config["sheets"].values()]})
            return self.response({"sheets": [{"properties": {"title": title, "sheetId": self.config["sheet_ids"][key],
                    "gridProperties": {"rowCount": 1000, "columnCount": 26}}}
                    for key, title in self.config["sheets"].items()]})
        self.read_count += 1
        if self.read_count == 1:
            return self.response({"valueRanges": [{"values": [["old"]] * 200}, {"values": [["old"]] * 50}]})
        entries = []
        for address in params["ranges"]:
            if self.read_count == 2:
                value = [["=SUM(A1)"]] if self.existing_formula and address == "'Balance Sheet'!C6" else []
            else:
                title, row, col, end_row, end_col = grid_address(address)
                value = [[self.cells.get((title, r, c), "") for c in range(col, end_col)] for r in range(row, end_row)]
                if self.corrupt_readback:
                    value[0][0] = "corrupted"
            entries.append({"range": address, "values": value})
        return self.response({"valueRanges": entries})

    def post(self, url, *, json, **kwargs):
        self.posted.append(json)
        ids = {value: self.config["sheets"][key] for key, value in self.config["sheet_ids"].items()}
        for request in json["requests"]:
            update = request["updateCells"]
            grid = update["range"]
            for i, row in enumerate(update["rows"]):
                for j, cell in enumerate(row["values"]):
                    data = cell.get("userEnteredValue", {})
                    self.cells[(ids[grid["sheetId"]], grid["startRowIndex"] + i, grid["startColumnIndex"] + j)] = next(iter(data.values()), "")
        return self.response({"replies": []})


def test_apply_backs_up_atomically_writes_only_values_and_clears_old_rows(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config)
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    assert Path(config["backup_path"]).is_file()
    assert len(session.posted) == 1
    requests = session.posted[0]["requests"]
    assert all(r["updateCells"]["fields"] == "userEnteredValue" for r in requests)
    assert session.cells[(config["sheets"]["notes"], 199, 0)] == ""
    assert (config["sheets"]["balancesheet"], 30, 2) not in session.cells


@pytest.mark.parametrize("option", ["validation", "existing_formula"])
def test_apply_refuses_constraints_and_unexpected_formulas_before_mutation(tmp_path, option):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config, **{option: True})
    with pytest.raises(ValueError):
        apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    assert not session.posted


def test_apply_never_reports_success_when_readback_differs(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config, corrupt_readback=True)
    with pytest.raises(ValueError, match="read-back differs"):
        apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    assert len(session.posted) == 1


def test_fixed_assets_list_failure_is_not_silently_empty():
    books = Mock()
    books.request.return_value = {"code": 57}
    with pytest.raises(ValueError):
        list(FixedAssets(books).list_iter())
