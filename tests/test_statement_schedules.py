from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from workflows.statement_schedules import build_schedule_plan, fetch_schedule_sources, validate_sources, verify_asset
from zoho.books.resources.fixed_assets import FixedAssets
from apps.update_statement_schedules import apply_plan, changed_update_requests, grid_address, main, note_bold_requests, update_requests
from workflows.statement_schedules.workflow import KEYS, nodes


def asset():
    return {"asset_account_id": "ledger", "asset_account_name": "Machinery", "fixed_asset_id": "asset", "asset_name": "Machine", "location_id": "branch", "location_name": "Branch",
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
    opening = deepcopy(reports["fy2024-25"]["balancesheet"])
    opening["page_context"]["to_date"] = "2024-03-31"
    reports["fy2024-25"]["balancesheet-opening"] = opening
    return config, sources


def test_plan_links_two_year_notes_and_does_not_write_statement_subtotals():
    config, sources = config_and_sources()
    plan = build_schedule_plan(sources, config)
    assert plan.checks["fy2025-26"]["assets"] == "100.00"
    assert plan.values["'Balance Sheet'!C6"][0][0].startswith("='Notes to Accounts'!B")
    assert plan.values["'Balance Sheet'!D6"][0][0].startswith("='Notes to Accounts'!C")
    assert "'Balance Sheet'!C31" not in plan.values
    assert "'Profit and Loss'!C19" not in plan.values


@pytest.mark.parametrize("reverse_periods", [False, True])
def test_note_groups_sum_signed_accounts_for_both_years(reverse_periods):
    config, sources = config_and_sources()
    note = next(n for n in config["notes"] if n["number"] == 9)
    note["groups"] = [{"name": "Cash", "account_ids": ["id9", "cash2"]},
                      {"name": "Bank", "account_ids": ["bank"]}]
    config["account_notes"].update({"cash2": 9, "bank": 9})
    for label, cash, bank in (("fy2025-26", -5, 30), ("fy2024-25", -2, 40)):
        report = sources["reports"][label]["balancesheet"][KEYS["balancesheet"]]
        for node, _ in nodes(report):
            if node.get("account_id") == "id9":
                node["total"] = cash
            elif node.get("account_id") == "id6":
                node["total"] = 100 - (cash + 10 + bank)
        report.extend([{"name": "Second cash", "account_id": "cash2", "total": 10},
                       {"name": "Bank account", "account_id": "bank", "total": bank}])
    if reverse_periods:
        config["periods"].reverse()
    plan = build_schedule_plan(sources, config)
    rows = next(rows for address, rows in plan.values.items() if address.startswith("'Notes to Accounts'!"))
    total_row = plan.note_total_rows[9]
    expected = [["Cash", 5.0, 8.0], ["Bank", 30.0, 40.0]]
    if reverse_periods:
        expected = [[name, prior, current] for name, current, prior in expected]
    assert rows[total_row - 3:total_row - 1] == expected
    assert rows[total_row - 1][1] == f"=SUM(B{total_row - 2}:B{total_row - 1})"
    assert plan.checks["fy2025-26"]["assets"] == "100.00"


def test_zero_note_groups_remain_visible():
    config, sources = config_and_sources()
    next(n for n in config["notes"] if n["number"] == 9)["groups"] = [
        {"name": "Cash", "account_ids": ["id9"]}, {"name": "Bank", "account_ids": ["absent"]}]
    plan = build_schedule_plan(sources, config)
    rows = next(rows for address, rows in plan.values.items() if address.startswith("'Notes to Accounts'!"))
    assert rows[plan.note_total_rows[9] - 3:plan.note_total_rows[9] - 1] == [["Cash", 0.0, 0.0], ["Bank", 0.0, 0.0]]


@pytest.mark.parametrize("bad", ["duplicate", "ungrouped", "empty", "name"])
def test_invalid_note_groups_fail_without_losing_nonzero_accounts(bad):
    config, sources = config_and_sources()
    note = next(n for n in config["notes"] if n["number"] == 6)
    note["groups"] = [{"name": "Assets", "account_ids": ["id6"]}]
    if bad == "duplicate":
        note["groups"].append({"name": "Duplicate", "account_ids": ["id6"]})
    elif bad == "ungrouped":
        note["groups"][0]["account_ids"] = ["other"]
    elif bad == "empty":
        note["groups"] = []
    else:
        note["groups"][0]["name"] = ""
    with pytest.raises(ValueError, match="Note 6"):
        build_schedule_plan(sources, config)


@pytest.mark.parametrize("reverse_periods", [False, True])
def test_assets_cover_only_latest_year_with_historical_opening(reverse_periods):
    config, sources = config_and_sources()
    record = asset() | {"asset_purchase_date": "2024-10-01", "depreciation_start_date": "2024-10-01"}
    rows = history()
    rows[0]["valuation_date"] = "2024-10-01"
    rows[1]["valuation_date"] = "2025-03-31"
    sources["assets"] = [{"asset": record, "history": rows}]
    if reverse_periods:
        config["periods"].reverse()
    plan = build_schedule_plan(sources, config)
    assert set(plan.asset_checks) == {"fy2025-26"}
    assert plan.asset_checks["fy2025-26"][0].opening == Decimal("925.21")
    asset_rows = next(rows for address, rows in plan.values.items() if address.startswith("'Assets & Depreciation'!"))
    assert asset_rows[0] == ["Assets & Depreciation — fy2025-26"]
    assert sum(row[0].startswith("Assets & Depreciation —") for row in asset_rows if row) == 1
    assert set(plan.checks) == {"fy2025-26", "fy2024-25"}
    assert "registered_asset_depreciation" not in plan.checks["fy2024-25"]


def test_current_year_asset_errors_still_stop_plan():
    config, sources = config_and_sources()
    sources["assets"] = [{"asset": asset() | {"depreciation_method": "straight_line"}, "history": history()}]
    with pytest.raises(ValueError):
        build_schedule_plan(sources, config)


@pytest.mark.parametrize("stocks", [(10, 20, 30), (30, 20, 10), (0, 0, 0), (20, 20, 20)])
def test_purchases_and_inventory_movement_preserve_cogs_and_profit(stocks):
    config, sources = config_and_sources()
    earlier, prior, current = stocks
    for label, closing in (("fy2025-26", current), ("fy2024-25", prior)):
        report = sources["reports"][label]
        for node, path in nodes(report["balancesheet"][KEYS["balancesheet"]]):
            if node.get("account_id") == "id7":
                node["total"] = closing
            elif node.get("account_id") == "id6":
                node["total"] = 100 - closing
        for node, path in nodes(report["profitandloss"][KEYS["profitandloss"]]):
            if node.get("account_id") == "id13":
                node["total"] = 50
            elif path == tuple(config["checks"]["profit_before_tax_path"]):
                node["total"] = -50
    opening = sources["reports"]["fy2024-25"]["balancesheet-opening"]
    for node, _ in nodes(opening[KEYS["balancesheet"]]):
        if node.get("account_id") == "id7":
            node["total"] = earlier
    plan = build_schedule_plan(sources, config)
    for label, initial, closing in (("fy2025-26", prior, current), ("fy2024-25", earlier, prior)):
        check = plan.checks[label]
        assert Decimal(check["net_purchases"]) == 50 - initial + closing
        assert Decimal(check["changes_in_inventories"]) == initial - closing
        assert Decimal(check["net_purchases"]) + Decimal(check["changes_in_inventories"]) == 50
        assert check["profit_before_tax"] == "-50.00"
    assert plan.values["'Profit and Loss'!C9"][0][0].endswith("-C8")
    assert plan.values["'Profit and Loss'!D9"][0][0].endswith("-D8")
    rows = next(rows for address, rows in plan.values.items() if "A1:C" in address)
    assert rows[plan.note_total_rows[13] - 1][0] == "Net purchases"


def test_opening_inventory_uses_account_overrides_outside_inventory_section():
    config, sources = config_and_sources()
    config["account_notes"]["outside"] = 7
    sources["reports"]["fy2024-25"]["balancesheet-opening"][KEYS["balancesheet"]].append(
        {"account_id": "outside", "name": "Mapped stock", "total": 25})
    plan = build_schedule_plan(sources, config)
    assert plan.checks["fy2024-25"]["opening_stock"] == "25.00"
    assert plan.checks["fy2024-25"]["net_purchases"] == "-25.00"
    assert plan.checks["fy2024-25"]["changes_in_inventories"] == "25.00"


@pytest.mark.parametrize("bad", ["missing", "date", "scope", "duplicate", "source_changes"])
def test_inventory_rollforward_rejects_missing_or_unverified_opening_and_double_counting(bad):
    config, sources = config_and_sources()
    prior = sources["reports"]["fy2024-25"]
    opening = prior["balancesheet-opening"]
    if bad == "missing":
        del prior["balancesheet-opening"]
    elif bad == "date":
        opening["page_context"]["to_date"] = "2025-03-31"
    elif bad == "scope":
        opening["page_context"]["rule"]["columns"][0]["value"] = ["other"]
    elif bad == "duplicate":
        opening[KEYS["balancesheet"]].append({"account_id": "id7", "name": "Duplicate stock", "total": 1})
    else:
        for node, path in nodes(prior["profitandloss"][KEYS["profitandloss"]]):
            if path[-1].startswith("3. Changes"):
                node["total"] = 1
    with pytest.raises(ValueError):
        build_schedule_plan(sources, config)


def test_fetch_reuses_prior_year_close_and_fetches_earliest_opening_once(monkeypatch):
    config, sources = config_and_sources()
    fetch = Mock(side_effect=[sources["reports"][p["label"]] for p in config["periods"]])
    monkeypatch.setattr("workflows.statement_schedules.workflow.fetch_schedule_reports", fetch)
    books = Mock(organization_id="org")
    books.fixed_assets.list_iter.return_value = []
    fetch_schedule_sources(books, periods=config["periods"], excluded_location_id="excluded", include_opening_inventory=True)
    assert "include_opening_balance_sheet" not in fetch.call_args_list[0].kwargs
    assert fetch.call_args_list[1].kwargs["include_opening_balance_sheet"] is True


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
        self.bold = {}
        for key, height in (("notes", 200), ("assets", 50)):
            for row in range(height):
                self.cells[(config["sheets"][key], row, 0)] = "old"

    def response(self, data):
        return Mock(json=lambda: data, raise_for_status=Mock())

    def get(self, url, *, params, **kwargs):
        if "values:batchGet" not in url:
            if params.get("includeGridData"):
                sheets = {title: {"properties": {"title": title}, "data": []}
                          for title in self.config["sheets"].values()}
                for address in params["ranges"]:
                    title, first_row, first_col, end_row, end_col = grid_address(address)
                    grid = {"startRow": first_row, "startColumn": first_col, "rowData": []}
                    for r in range(first_row, end_row):
                        row = []
                        for c in range(first_col, end_col):
                            value = self.cells.get((title, r, c), "")
                            field = "numberValue" if isinstance(value, (int, float)) else "formulaValue" if value.startswith("=") else "stringValue"
                            cell = {"userEnteredValue": {field: value}} if value != "" else {}
                            cell["userEnteredFormat"] = {"textFormat": {"bold": self.bold.get((title, r, c), False)}}
                            if self.validation:
                                cell["dataValidation"] = {"strict": True}
                            row.append(cell)
                        grid["rowData"].append({"values": row})
                    sheets[title]["data"].append(grid)
                return self.response({"sheets": list(sheets.values())})
            return self.response({"sheets": [{"properties": {"title": title, "sheetId": self.config["sheet_ids"][key],
                    "gridProperties": {"rowCount": 1000, "columnCount": 26}}}
                    for key, title in self.config["sheets"].items()]})
        self.read_count += 1
        if self.read_count == 1:
            return self.response({"valueRanges": [{"values": [["old"]] * 200}, {"values": [["old"]] * 50}]})
        entries = []
        for address in params["ranges"]:
            if self.read_count == 2:
                value = [[self.existing_formula if isinstance(self.existing_formula, str) else "=SUM(A1)"]] if self.existing_formula and address == "'Balance Sheet'!C6" else []
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
                    if update["fields"] == "userEnteredFormat.textFormat.bold":
                        self.bold[(ids[grid["sheetId"]], grid["startRowIndex"] + i, grid["startColumnIndex"] + j)] = cell["userEnteredFormat"]["textFormat"]["bold"]
                        continue
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
    assert {r["updateCells"]["fields"] for r in requests} == {"userEnteredValue", "userEnteredFormat.textFormat.bold"}
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


def test_apply_accepts_previous_generated_note_link_after_note_rows_move(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config, existing_formula="='Notes to Accounts'!B999")
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    assert len(session.posted) == 1


@pytest.mark.parametrize("existing,accepted", [("='Notes to Accounts'!B999-C8", True),
    ("='Notes to Accounts'!B999-C7", False), ("=SUM(A1)", False)])
def test_apply_moving_inventory_movement_formula(tmp_path, existing, accepted):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    class MovementSession(SheetsSession):
        def get(self, url, *, params, **kwargs):
            response = super().get(url, params=params, **kwargs)
            if "values:batchGet" in url and self.read_count == 2:
                for entry in response.json()["valueRanges"]:
                    if entry["range"] == "'Profit and Loss'!C9":
                        entry["values"] = [[existing]]
            return response
    session = MovementSession(config)
    if accepted:
        apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
        assert len(session.posted) == 1
    else:
        with pytest.raises(ValueError, match="Unexpected existing formula"):
            apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
        assert session.posted == []


def test_apply_identical_plan_performs_no_write(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config)
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    session.posted.clear()
    session.read_count = 0
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    assert session.posted == []


def test_apply_second_run_writes_only_changed_cell(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    plan = build_schedule_plan(sources, config)
    session = SheetsSession(config)
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    session.cells[(config["sheets"]["notes"], 0, 0)] = "Different company"
    session.posted.clear()
    session.read_count = 0
    apply_plan("spreadsheet", plan.values, access_token="mock-token", config=config, session=session)
    writes = session.posted[0]["requests"]
    assert len(writes) == 1
    assert writes[0]["updateCells"]["range"] == {
        "sheetId": config["sheet_ids"]["notes"], "startRowIndex": 0, "endRowIndex": 1,
        "startColumnIndex": 0, "endColumnIndex": 1}


def test_changed_cells_preserve_entered_types_and_split_at_unchanged_cells():
    config, _ = config_and_sources()
    requests = update_requests({"'Notes to Accounts'!A3:C3": [["=literal", 0, "=1+1"]]}, config)
    native = {"sheets": [{"properties": {"title": config["sheets"]["notes"]}, "data": [
        {"startRow": 2, "rowData": [{"values": [
            {"userEnteredValue": {"formulaValue": "=literal"}},
            {"userEnteredValue": {"numberValue": 0.0}},
            {"userEnteredValue": {"stringValue": "=1+1"}}]}]}]}]}
    writes = changed_update_requests(requests, native, config)
    assert len(writes) == 2
    assert [w["updateCells"]["range"]["startColumnIndex"] for w in writes] == [0, 2]
    assert writes[0]["updateCells"]["rows"][0]["values"][0] == {"userEnteredValue": {"stringValue": "=literal"}}


def test_fixed_assets_list_failure_is_not_silently_empty():
    books = Mock()
    books.request.return_value = {"code": 57}
    with pytest.raises(ValueError):
        list(FixedAssets(books).list_iter())


def test_note_bold_tracks_moved_headers_and_clears_totals_and_stale_rows():
    config, _ = config_and_sources()
    values = {"'Notes to Accounts'!A1:C4": [["Note 7: Inventory", "", ""], ["Inventory Asset", 1, 2], ["Total", 1, 2], ["", "", ""]]}
    native = {"sheets": [{"properties": {"title": config["sheets"]["notes"]}, "data": [{"rowData": [
        {"values": [{"effectiveFormat": {"textFormat": {"bold": True}}}]},
        {"values": [{"userEnteredFormat": {"textFormat": {"bold": True}}}]},
        {"values": [{"effectiveFormat": {"textFormat": {"bold": True}}}]},
        {"values": [{"userEnteredFormat": {"textFormat": {"bold": True}}}]}]}]}]}
    writes = note_bold_requests(values, native, config)
    assert [(w["updateCells"]["range"]["startRowIndex"], w["updateCells"]["range"]["startColumnIndex"]) for w in writes] == [(0, 1), (0, 2), (1, 0), (2, 0), (3, 0)]
    assert all(w["updateCells"]["fields"] == "userEnteredFormat.textFormat.bold" for w in writes)


def test_apply_refuses_success_when_bold_readback_differs(tmp_path):
    config, sources = config_and_sources()
    config["backup_path"] = str(tmp_path / "backup.json")
    class BadBoldSession(SheetsSession):
        def post(self, *args, **kwargs):
            response = super().post(*args, **kwargs)
            self.bold.clear()
            return response
    with pytest.raises(ValueError, match="bold formatting read-back differs"):
        apply_plan("spreadsheet", build_schedule_plan(sources, config).values, access_token="mock", config=config, session=BadBoldSession(config))


def test_asset_tables_group_opening_by_ledger_and_keep_individual_calculations():
    config, sources = config_and_sources()
    record = asset() | {"asset_purchase_date": "2024-10-01", "depreciation_start_date": "2024-10-01"}
    rows = history()
    rows[0]["valuation_date"] = "2024-10-01"
    rows[1]["valuation_date"] = "2025-03-31"
    sources["assets"] = [{"asset": record, "history": rows},
                         {"asset": record | {"fixed_asset_id": "second", "asset_name": "Second"}, "history": rows}]
    plan = build_schedule_plan(sources, config)
    table = next(rows for address, rows in plan.values.items() if address.startswith("'Assets & Depreciation'!"))
    assert table[3] == ["Machine", "Machinery", 925.21]
    assert table[4] == ["Second", "Machinery", 925.21]
    assert table[5] == ["Subtotal", "Machinery", "=SUM(C4:C5)"]
    assert table[6] == ["Total", "", "=SUM(C6)"]
    assert len([row for row in table if row and str(row[0]).startswith("Table ")]) == 2
    r, summary = next((i + 1, row) for i, row in enumerate(table) if row and row[0] == "Machinery")
    assert summary[1] == "=C6"
    assert summary[4] == f"=SUM(B{r}:D{r})"
    assert "C4" in summary[7] and "C5" in summary[7] and summary[7].count("ROUND(") == 2
    assert summary[6] == f"=E{r}-F{r}"
    assert summary[11] == 0.15


@pytest.mark.parametrize("field", ["asset_account_id", "asset_account_name"])
def test_asset_grouping_refuses_missing_ledger_account(field):
    config, sources = config_and_sources()
    record = asset()
    record.pop(field)
    sources["assets"] = [{"asset": record, "history": history()}]
    with pytest.raises(ValueError, match="Missing ledger account"):
        build_schedule_plan(sources, config)


def test_asset_expense_uses_posted_values_and_reconciles_to_pnl():
    config, sources = config_and_sources()
    sources["assets"] = [{"asset": asset(), "history": history()}]
    plan = build_schedule_plan(sources, config)
    rows = next(v for a, v in plan.values.items() if a.startswith("'Assets & Depreciation'!"))
    r, detail = next((i + 1, row) for i, row in enumerate(rows) if row and row[0] == "Machinery")
    assert detail[5] == float(plan.asset_checks["fy2025-26"][0].posted)
    assert detail[6] == f"=E{r}-F{r}"
    assert detail[7].startswith("=SUM(ROUND(")
    assert next(row for row in rows if row and row[0] == "P&L depreciation expense")[5] == "='Profit and Loss'!C12"


def test_asset_ledger_override_moves_subtotal_without_changing_register():
    config, sources = config_and_sources()
    sources["assets"] = [{"asset": asset() | {"asset_account_name": "Wrong ledger"}, "history": history()}]
    before = build_schedule_plan(sources, config)
    config["asset_ledger_overrides"] = {"asset": {"account_id": "correct", "account_name": "Machinery"}}
    after = build_schedule_plan(sources, config)
    assert after.checks == before.checks
    assert after.asset_checks == before.asset_checks
    rows = next(v for a, v in after.values.items() if a.startswith("'Assets & Depreciation'!"))
    assert ["Machine", "Machinery", 0.0] in rows
    assert not any("Wrong ledger" in r for r in rows)


def test_opening_reclassification_preserves_total_basis_and_depreciation():
    config, sources = config_and_sources()
    record = asset() | {"asset_purchase_date": "2025-04-01", "depreciation_start_date": "2025-04-01"}
    rows = history()
    rows[0]["valuation_date"] = "2025-04-01"
    sources["assets"] = [{"asset": record, "history": rows}]
    before = build_schedule_plan(sources, config)
    config["asset_opening_reclassifications"] = {"asset": 1000}
    after = build_schedule_plan(sources, config)
    original = before.asset_checks["fy2025-26"][0]
    corrected = after.asset_checks["fy2025-26"][0]
    assert corrected.opening == 1000 and corrected.before_cutoff == 0
    assert corrected.calculated == original.calculated
    assert corrected.posted == original.posted
    assert corrected.closing == original.closing
    assert after.checks == before.checks


def test_ledger_only_asset_is_visible_without_invented_depreciation():
    config, sources = config_and_sources()
    config["ledger_only_assets"] = [{"name": "Bike", "account_id": "id6", "account_name": "Vehicles"}]
    plan = build_schedule_plan(sources, config)
    rows = next(v for a, v in plan.values.items() if a.startswith("'Assets & Depreciation'!"))
    assert ["Bike", "Vehicles", 100.0] in rows
    summary = next(r for r in rows if r and r[0] == "Vehicles")
    assert summary[5] == summary[7] == ""
    assert summary[6] == summary[9] == 100.0
    assert any("ledger-only asset" in w for w in plan.warnings)
    config["ledger_only_assets"][0]["account_id"] = "missing"
    with pytest.raises(ValueError, match="Missing ledger-only"):
        build_schedule_plan(sources, config)


def test_ledger_opening_uses_prior_year_balances_and_preserves_basis():
    config, sources = config_and_sources()
    record = asset() | {"asset_account_id": "id6", "asset_account_name": "Account6",
                        "asset_purchase_date": "2025-04-01", "depreciation_start_date": "2025-04-01"}
    rows = history()
    rows[0]["valuation_date"] = "2025-04-01"
    sources["assets"] = [{"asset": record, "history": rows}]
    config["asset_opening_source"] = "ledger"
    plan = build_schedule_plan(sources, config)
    result = plan.asset_checks["fy2025-26"][0]
    assert result.opening == 100 and result.before_cutoff == 900
    table = next(v for a, v in plan.values.items() if a.startswith("'Assets & Depreciation'!"))
    assert ["Machine", "Account6", 100.0] in table
    sources["assets"].append({"asset": record | {"fixed_asset_id": "second"}, "history": rows})
    with pytest.raises(ValueError, match="reviewed asset allocation"):
        build_schedule_plan(sources, config)


def test_ledger_opening_refuses_duplicate_accumulated_depreciation_assignment():
    config, sources = config_and_sources()
    config["asset_opening_source"] = "ledger"
    config["asset_accumulated_depreciation_accounts"] = {"id6": ["dep"], "other": ["dep"]}
    with pytest.raises(ValueError, match="assigned twice"):
        build_schedule_plan(sources, config)
