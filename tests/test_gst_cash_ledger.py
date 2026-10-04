from decimal import Decimal
import pytest
from workflows.gst_cash_ledger import check_gst_cash_ledger


def report():
    return {'code': 0, 'page_context': {'cash_based': 'false'}, 'balance_sheet': [
        {'name': name, 'total': value} for tax in ('CGST', 'SGST', 'IGST', 'CESS')
        for name, value in [(f'Cash Ledger : {tax} Tax', 20), (f'Output {tax}', 120), (f'Input {tax}', 100)]]}


def test_matches_and_tolerance():
    data = report()
    assert not any(c.mismatch for c in check_gst_cash_ledger(data))
    data['balance_sheet'][0]['total'] = '20.01'
    assert not check_gst_cash_ledger(data)[0].mismatch
    data['balance_sheet'][0]['total'] = '20.02'
    assert check_gst_cash_ledger(data)[0].difference == Decimal('.02')
    assert check_gst_cash_ledger(data)[0].mismatch


def test_unrelated_repeated_report_names_are_ignored():
    data = report()
    data['balance_sheet'] += [{'name': 'Accounts Receivable', 'total': 0}] * 2
    assert not any(c.mismatch for c in check_gst_cash_ledger(data))


def test_negative_net_credit_and_nested_accounts():
    data = report()
    data['balance_sheet'][0]['total'] = -20
    data['balance_sheet'][1]['total'] = 80
    data['balance_sheet'] = [{'name': 'Assets', 'total': 0, 'account_transactions': data['balance_sheet']}]
    assert not check_gst_cash_ledger(data)[0].mismatch


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'nonfinite', 'cash', 'error'])
def test_invalid_reports_fail(change):
    data = report()
    if change == 'missing': data['balance_sheet'].pop()
    if change == 'duplicate': data['balance_sheet'].append(data['balance_sheet'][0])
    if change == 'nonfinite': data['balance_sheet'][0]['total'] = 'NaN'
    if change == 'cash': data['page_context']['cash_based'] = 'true'
    if change == 'error': data['code'] = 1
    with pytest.raises(ValueError): check_gst_cash_ledger(data)


@pytest.mark.parametrize('tolerance', [Decimal('-1'), Decimal('NaN')])
def test_invalid_tolerance(tolerance):
    with pytest.raises(ValueError): check_gst_cash_ledger(report(), tolerance=tolerance)
