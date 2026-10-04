"""Read-only GST cash-ledger versus net GST balance reconciliation."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class GSTCashLedgerCheck:
    tax: str
    cash_ledger: Decimal
    output_gst: Decimal
    input_gst: Decimal
    expected: Decimal
    difference: Decimal
    mismatch: bool


def check_gst_cash_ledger(report: Mapping[str, Any], *, tolerance: Decimal = Decimal('0.01')) -> list[GSTCashLedgerCheck]:
    """Compare closing balance-sheet amounts; difference is cash minus net GST.

    Uses Tax cash ledgers only, excluding interest and late fees. Input and cash
    balances use Books asset presentation; output uses liability presentation.
    This is the requested balance equality, not a verification of filed returns.
    """
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError('Tolerance must be finite and nonnegative')
    if report.get('code') != 0 or not isinstance(report.get('balance_sheet'), list):
        raise ValueError('Successful Books balance sheet required')
    context = report.get('page_context', {})
    if str(context.get('cash_based')).lower() != 'false':
        raise ValueError('Accrual balance sheet required')
    amounts: dict[str, Decimal] = {}
    target_names = {name for tax in ('CGST', 'SGST', 'IGST', 'CESS')
                    for name in (f'Cash Ledger : {tax} Tax', f'Output {tax}', f'Input {tax}')}

    def visit(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            name = node['name']
            if name in target_names and name in amounts:
                raise ValueError('Ambiguous account name: ' + name)
            amount = Decimal(str(node['total']))
            if not amount.is_finite():
                raise ValueError('Non-finite balance: ' + name)
            if name in target_names:
                amounts[name] = amount
            visit(node.get('account_transactions', []))

    visit(report['balance_sheet'])
    checks = []
    for tax in ('CGST', 'SGST', 'IGST', 'CESS'):
        names = (f'Cash Ledger : {tax} Tax', f'Output {tax}', f'Input {tax}')
        missing = [name for name in names if name not in amounts]
        if missing:
            raise ValueError('Missing GST accounts: ' + ', '.join(missing))
        cash, output, input_tax = (amounts[name] for name in names)
        expected = output - input_tax
        difference = cash - expected
        checks.append(GSTCashLedgerCheck(tax, cash, output, input_tax, expected, difference, abs(difference) > tolerance))
    return checks


def fetch_gst_cash_ledger_report(books: Any, *, from_date: str, to_date: str, firm: str | None = None) -> Mapping[str, Any]:
    from workflows.audited_financials.reports import _firm_rule
    import json
    if date.fromisoformat(from_date) > date.fromisoformat(to_date):
        raise ValueError('Start date must not follow end date')
    rule = _firm_rule(firm, None)
    report = books.request('GET', 'reports/balancesheet', params={
        'filter_by': 'TransactionDate.CustomDate', 'from_date': from_date,
        'to_date': to_date, 'cash_based': 'false', 'show_rows': 'all',
        'is_expand': 'true', 'rule': json.dumps(rule)})
    if report.get('page_context', {}).get('to_date') != to_date:
        raise ValueError('Books report date does not match')
    applied = report.get('page_context', {}).get('rule', {})
    if applied.get('criteria_string') != rule['criteria_string'] or any(
        any(actual.get(k) != expected.get(k) for k in ('index', 'field', 'value', 'comparator', 'group'))
        for actual, expected in zip(applied.get('columns', []), rule['columns'])
    ) or len(applied.get('columns', [])) != len(rule['columns']):
        raise ValueError('Books report location scope does not match')
    return report
