from copy import deepcopy
from decimal import Decimal
from datetime import datetime
import json

import openpyxl
import pytest

from workflows.audited_financials import (
    ComparisonPeriod, compare_audited_financials, fetch_comparison_reports,
    load_accounting_mapping, read_audited_workbook, validate_report,
)
from apps import compare_audited_financials as app


PERIOD = ComparisonPeriod("2024-04-01", "2025-03-31")


def node(name, total=0, children=()):
    return {"name": name, "total": total, "account_transactions": list(children)}


@pytest.fixture
def inputs():
    sheets = {"Trading & P&L": [(f"Line {i}", 0) for i in range(1, 40)],
              "Balance Sheet": [(f"Line {i}", 0) for i in range(1, 31)]}
    for row in (6, 8, 17, 34, 39):
        sheets["Trading & P&L"][row-1] = (f"Line {row}", 100)
    pl = [node("Gross Profit", 120, [node("Operating Income", 120, [node("Sales", 120)]),
          node("Non Operating Income"), node("Cost of Goods Sold", children=[node("Zero purchase")])]),
          node("Operating Expense"), node("Non Operating Expense"), node("Net Profit/Loss", 120)]
    bs = [node(name) for name in ("Assets", "Input CGST", "Input IGST", "Input SGST",
          "Output CGST", "Output IGST", "Output SGST", "Retained Earnings", "Current Year Earnings")]
    trial = [{"name": "Stock", "opening_balance": "10 Dr", "net_debit": 0,
              "net_credit": 0, "closing_balance": "10 Dr"}]
    context = {"from_date": PERIOD.from_date, "to_date": PERIOD.to_date, "cash_based": "false"}
    reports = {}
    for name, key, rows in [("profitandloss", "profit_and_loss", pl),
                           ("balancesheet", "balance_sheet", bs),
                           ("trialbalance", "trialbalance", trial)]:
        reports[name] = {"code": 0, "page_context": deepcopy(context), key: rows}
        if name != "trialbalance":
            reports[name+"-all-locations"] = deepcopy(reports[name])
    calculations = {name: {} for name in ("interest", "freight", "op", "other_income")}
    calculations.update({"sales": {"accounts": {"Sales": 1}},
        "income": {"accounts": {"Operating Income": 1, "Non Operating Income": 1}},
        "cogs": {"path": ["Gross Profit", "Cost of Goods Sold"]},
        "gross": {"derived": {"income": 1, "cogs": -1}},
        "operating": {"derived": {"gross": 1, "op": -1}}})
    return sheets, reports, {"calculations": calculations, "pnl_expense_accounts": {}, "balance_sheet_accounts": {"18": ["Assets"]}}


def compare(inputs):
    return compare_audited_financials(*inputs, PERIOD, source_name="audit.xlsx")


def test_pending_expense_is_excluded_and_remains_unmapped(inputs):
    inputs[1]['profitandloss']['profit_and_loss'].append(
        node('Operating Expense', 10, [dict(node('Pending tax', 10), account_id='tax-id')])
    )
    inputs[2]['calculations']['op'] = {'accounts': {'Operating Expense': 1}}
    inputs[2]['excluded_pnl_expense_accounts'] = ['Pending tax']
    for item in inputs[1]['profitandloss']['profit_and_loss']:
        if item['name'] == 'Net Profit/Loss':
            item['total'] = 110
    result = compare(inputs)
    assert '| Line 32 (B32) | 0.00 | 0.00 |' in result.markdown
    assert '| Line 30 (B30) | 0.00 | 0.00 |' in result.markdown
    assert '| Pending tax | tax-id | 10.00 Dr | Excluded from audited operating expenses; mapping pending |' in result.markdown
    assert result.net_profit_difference == Decimal(10)


def test_net_gst_excludes_input_from_both_statement_totals(inputs):
    inputs[2]['net_gst_in_balance_sheet_totals'] = True
    inputs[2]['balance_sheet_accounts']['28'] = ['Liabilities & Equities']
    bs = inputs[1]['balancesheet']['balance_sheet']
    bs.append(node('Liabilities & Equities', 100))
    for item in bs:
        if item['name'] == 'Assets':
            item['total'] = 100
        elif item['name'] == 'Input CGST':
            item['total'] = 20
        elif item['name'] == 'Output CGST':
            item['total'] = 30
    result = compare(inputs)
    assert result.assets_difference == Decimal(80)
    assert '| Line 18 (B18) | 0.00 | 80.00 |' in result.markdown
    assert '| Line 28 (B28) | 0.00 | 80.00 |' in result.markdown
    assert '| Line 26 (B26) | 0.00 | 10.00 |' in result.markdown
    assert next(item['total'] for item in bs if item['name'] == 'Assets') == 100


def test_audited_gst_asset_regroups_into_fixed_assets(inputs):
    inputs[0]['Balance Sheet'][5] = ('Fixed Assets', -10)
    inputs[0]['Balance Sheet'][14] = ('GST', 10)
    inputs[2]['balance_sheet_accounts']['6'] = ['Assets']
    inputs[2]['audited_gst_asset_to_fixed_assets'] = True
    result = compare(inputs)
    assert '| Fixed Assets (B6) | 0.00 | 0.00 |' in result.markdown
    assert '| GST (B15) | 0.00 |' in result.markdown
    assert 'Audited source amount 10.00 regrouped' in result.markdown
    assert result.assets_difference == 0
    assert inputs[0]['Balance Sheet'][14][1] == 10


def test_report_has_stock_zero_cogs_unmapped_and_difference(inputs):
    result = compare(inputs)
    assert result.net_profit_difference == Decimal(20)
    assert result.assets_difference == 0
    for text in ("(B11)", "(B14)", "Stock | 10 Dr | 0 | 0 | 10 Dr",
                 "Zero purchase | 0.00", "Line 9 (B9)", "ledger confirmation required"):
        assert text in result.markdown
    inputs[2]["calculations"]["sales"]["accounts"]["Sales"] = -1
    assert "| Line 6 (B6) | 100.00 | -120.00 | 220.00 Dr" in compare(inputs).markdown


@pytest.mark.parametrize('delta', [Decimal('20'), Decimal('-20'), Decimal('0')])
def test_difference_sides_follow_accounting_nature(inputs, delta):
    sheets, reports, config = inputs
    config['pnl_expense_accounts'] = {'20': ['Operating Expense']}
    config['balance_sheet_accounts'].update({'6': ['Assets'], '21': ['Retained Earnings']})
    # Offset audited expenses with an expense credit to preserve audited arithmetic.
    sheets['Trading & P&L'][19] = ('Expense', -delta)
    sheets['Trading & P&L'][20] = ('Offset', delta)
    # Equal audited asset and liability changes preserve the balance sheet.
    for row in (6, 18, 21, 28):
        sheets['Balance Sheet'][row - 1] = (f'Line {row}', -delta)
    markdown = compare(inputs).markdown
    debit = '0.00' if delta == 0 else f'{abs(delta):,.2f} ' + ('Dr' if delta > 0 else 'Cr')
    credit = '0.00' if delta == 0 else f'{abs(delta):,.2f} ' + ('Cr' if delta > 0 else 'Dr')
    assert f'| Expense (B20) | {-delta:,.2f} | 0.00 | {debit} |' in markdown
    assert f'| Line 6 (B6) | {-delta:,.2f} | 0.00 | {debit} |' in markdown
    assert f'| Line 21 (B21) | {-delta:,.2f} | 0.00 | {credit} |' in markdown
    assert '| Line 6 (B6) | 100.00 | 120.00 | 20.00 Cr |' in markdown
    assert 'opposite side' in markdown


def test_creation_timestamp_is_at_top_with_timezone(inputs):
    before = datetime.now().astimezone().replace(microsecond=0)
    lines = compare(inputs).markdown.splitlines()
    after = datetime.now().astimezone()
    assert lines[2].startswith("**Report created:** ")
    created = datetime.fromisoformat(lines[2].removeprefix("**Report created:** "))
    assert created.utcoffset() is not None
    assert before <= created <= after


def test_unmatched_accounts_ignore_headline_totals_but_honor_groups(inputs):
    bs = inputs[1]['balancesheet']['balance_sheet']
    bs[0]['account_transactions'] = [dict(node('Unmapped asset', 10), account_id='asset-1'),
                                    dict(node('Zero asset', 0), account_id='asset-zero'),
                                    dict(node('Rounded zero asset', 0.001), account_id='asset-tiny'),
                                    node('Mapped group', 0, [dict(node('Grouped asset', 0), account_id='asset-2')])]
    inputs[2]['balance_sheet_accounts']['6'] = ['Mapped group']
    pl = inputs[1]['profitandloss']['profit_and_loss']
    pl[1]['account_transactions'] = [dict(node('Residual expense', -10), account_id='expense-1')]
    markdown = compare(inputs).markdown.split('## Books accounts without an audited match')[1]
    assert '| Unmapped asset | asset-1 | 10.00 Dr | No mapped audited line |' in markdown
    assert 'Zero asset' not in markdown and 'Rounded zero asset' not in markdown
    assert '| Residual expense | expense-1 | 10.00 Cr |' in markdown
    assert 'Residual expense' in markdown and 'Other Expenses residual' in markdown
    assert 'Grouped asset' not in markdown


@pytest.mark.parametrize('report,section,normal_side', [
    ('profitandloss', 'Non Operating Income', 'Cr'),
    ('profitandloss', 'Non Operating Expense', 'Dr'),
    ('balancesheet', 'Assets', 'Dr'),
    ('balancesheet', 'Liabilities', 'Cr'),
    ('balancesheet', 'Equities', 'Cr'),
])
@pytest.mark.parametrize('amount', [10, -10])
def test_unmatched_account_balance_sides(inputs, report, section, normal_side, amount):
    key = 'profit_and_loss' if report == 'profitandloss' else 'balance_sheet'
    inputs[1][report][key].append(node(section, children=[
        dict(node('Unmatched balance', amount), account_id='unmatched-id')
    ]))
    side = normal_side if amount > 0 else ('Cr' if normal_side == 'Dr' else 'Dr')
    markdown = compare(inputs).markdown.split('## Books accounts without an audited match')[1]
    assert f'| Unmatched balance | unmatched-id | 10.00 {side} |' in markdown


@pytest.mark.parametrize('output,input_tax,net', [(150, 100, '50.00'), (100, 150, '-50.00'), (100, 100, '0.00')])
def test_gst_payable_is_output_minus_input(inputs, output, input_tax, net):
    for item in inputs[1]['balancesheet']['balance_sheet']:
        if item['name'] == 'Output CGST':
            item['total'] = output
        if item['name'] == 'Input CGST':
            item['total'] = input_tax
    inputs[2]['balance_sheet_accounts']['26'] = ['Output CGST']
    markdown = compare(inputs).markdown
    assert f'| Line 26 (B26) | 0.00 | {net} |' in markdown
    assert markdown.count('| Line 26 (B26)') == 1
    assert 'Output GST minus Input GST' in markdown


@pytest.mark.parametrize('amount', [25, -25, 0])
def test_balance_sheet_adds_reviewed_pnl_accounts(inputs, amount):
    inputs[2]['balance_sheet_accounts']['12'] = ['Assets']
    inputs[2]['balance_sheet_pnl_accounts'] = {'12': ['Tax expense']}
    inputs[1]['profitandloss']['profit_and_loss'].append(node('Tax expense', amount))
    result = compare(inputs)
    side = '0.00' if amount == 0 else f'{abs(amount):,.2f} ' + ('Dr' if amount > 0 else 'Cr')
    assert f'| Line 12 (B12) | 0.00 | {amount:,.2f} | {side} | Assets + Tax expense (P&L; reviewed regrouping) |' in result.markdown
    assert result.assets_difference == 0
    assert result.net_profit_difference == 20


def test_balance_sheet_pnl_mapping_rejects_missing_row_or_account(inputs):
    inputs[2]['balance_sheet_pnl_accounts'] = {'12': ['Unknown tax']}
    with pytest.raises(ValueError, match='require a balance_sheet_accounts row'):
        compare(inputs)
    inputs[2]['balance_sheet_accounts']['12'] = ['Assets']
    with pytest.raises(ValueError, match='Unknown mapped Books accounts: Unknown tax'):
        compare(inputs)


@pytest.mark.parametrize("field,value", [("to_date", "2026-03-31"), ("from_date", "2025-04-01"), ("cash_based", "true")])
def test_saved_report_context_rejected(inputs, field, value):
    inputs[1]["profitandloss"]["page_context"][field] = value
    with pytest.raises(ValueError, match="match"):
        compare(inputs)


def test_circular_and_missing_mapping(inputs):
    inputs[2]["calculations"]["sales"] = {"derived": {"sales": 1}}
    with pytest.raises(ValueError, match="Circular"):
        compare(inputs)
    inputs[2]["calculations"]["sales"] = {"accounts": {"Unknown": 1}}
    with pytest.raises(ValueError, match="Unknown mapped"):
        compare(inputs)


def test_ambiguous_account_names_are_rejected(inputs):
    income = inputs[1]["profitandloss"]["profit_and_loss"][0]["account_transactions"][0]
    income["account_transactions"] = [dict(node("Sales", 60), account_id="a"),
                                       dict(node("Sales", 60), account_id="b")]
    with pytest.raises(ValueError, match="Ambiguous Books account name"):
        compare(inputs)


def test_invalid_trial_and_source_rejected(inputs):
    del inputs[1]["trialbalance"]["trialbalance"][0]["opening_balance"]
    with pytest.raises(ValueError, match="Missing trial balance column"):
        compare(inputs)
    inputs[0]["Balance Sheet"][17] = ("Total", 5)
    with pytest.raises(ValueError, match="arithmetic"):
        compare(inputs)


def test_fetch_reads_all_reports_with_scope(inputs):
    calls = []
    class Client:
        def request(self, method, endpoint, *, params):
            calls.append((method, endpoint, params))
            report = deepcopy(inputs[1][endpoint.split("/")[-1]])
            if "rule" in params:
                report["page_context"]["rule"] = json.loads(params["rule"])
                report["page_context"]["rule"]["columns"][0]["display_name"] = "Location"
            return report
    reports = fetch_comparison_reports(Client(), PERIOD, ("excluded",))
    assert len(reports) == 5
    assert all(method == "GET" for method, _, _ in calls)
    assert sum("rule" in params for _, _, params in calls) == 3
    class BadClient:
        def request(self, method, endpoint, *, params):
            return inputs[1][endpoint.split("/")[-1]]
    with pytest.raises(ValueError, match="echo"):
        fetch_comparison_reports(BadClient(), PERIOD, ("excluded",))


def test_saved_cli_never_authenticates(inputs, tmp_path, monkeypatch):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in inputs[0].items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    source = tmp_path / "audit.xlsx"
    workbook.save(source)
    workbook.close()
    assert read_audited_workbook(source) == inputs[0]
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(json.dumps(inputs[2]), encoding="utf-8")
    for name, report in inputs[1].items():
        (tmp_path / f"{name}.json").write_text(json.dumps(report), encoding="utf-8")
    def forbidden():
        pytest.fail("Saved mode must not authenticate")
    monkeypatch.setattr(app, "get_books_client", forbidden)
    original = source.read_bytes()
    assert app.main(["--source", str(source), "--mapping", str(mapping), "--saved", "--snapshots", str(tmp_path)]) == 0
    assert source.read_bytes() == original
    assert (tmp_path / "audited-financials-vs-books-fy24-25.md").exists()


def test_bad_period_mapping_and_api(tmp_path):
    with pytest.raises(ValueError):
        ComparisonPeriod("2025-03-31", "2024-04-01")
    path = tmp_path / "bad.yaml"
    path.write_text("[]")
    with pytest.raises(ValueError, match="Mapping needs"):
        load_accounting_mapping(path)
    with pytest.raises(ValueError, match="failed"):
        validate_report({"code": 57, "message": "denied"}, "profitandloss", PERIOD)

def test_comparison_uses_configured_scope_for_every_filtered_report(inputs, tmp_path):
    config = tmp_path / "firms.yaml"
    config.write_text(json.dumps({"default_firm": "TEST", "firms": {"TEST": {
        "name": "Test firm", "gstin": "TESTGST", "scope": {
            "comparator": "in", "location_ids": ["branch"]}}}}), encoding="utf-8")
    calls = []
    class Client:
        def request(self, method, endpoint, *, params):
            calls.append((endpoint, params))
            result = deepcopy(inputs[1][endpoint.split("/")[-1]])
            if "rule" in params:
                result["page_context"]["rule"] = json.loads(params["rule"])
            return result
    result = fetch_comparison_reports(Client(), PERIOD, firm_config=config)
    assert "trialbalance" in result
    assert not any("horizontal" in endpoint for endpoint, _ in calls)
    scoped = [json.loads(params["rule"]) for _, params in calls if "rule" in params]
    assert len(scoped) == 3
    assert all(rule["columns"][0]["comparator"] == "in" for rule in scoped)
    assert all(rule["columns"][0]["value"] == ["branch"] for rule in scoped)

def test_saved_requires_trial_balance_snapshot(inputs):
    del inputs[1]["trialbalance"]
    with pytest.raises(ValueError, match="Missing report snapshots: trialbalance"):
        compare(inputs)


def test_live_trial_balance_tree_and_formatted_values(inputs):
    inputs[1]["trialbalance"]["trialbalance"] = {"name": "Trial Balance", "accounts": [
        {"name": "Assets", "accounts": [{"name": "Stock", "account_id": "stock", "values": [{
            "opening_balance": 10, "opening_balance_formatted": "10.00 Dr", "net_debit": 2,
            "net_credit": 1, "closing_balance": 11, "closing_balance_formatted": "11.00 Dr"}]}]}]}
    assert "Stock | 10.00 Dr | 2 | 1 | 11.00 Dr" in compare(inputs).markdown
