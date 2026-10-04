"""Monthly GST movements versus following-month cash tax debits."""
from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from decimal import Decimal
from typing import Any, Mapping
from workflows.core.matching import to_finite_decimal


@dataclass(frozen=True)
class MonthlyGSTCheck:
    tax: str
    output: Decimal
    input: Decimal
    net: Decimal
    next_month_cash_debits: Decimal
    difference: Decimal


def month_bounds(year: int, month: int) -> tuple[str, str]:
    return date(year, month, 1).isoformat(), date(year, month, monthrange(year, month)[1]).isoformat()


def gst_movements(report: Mapping[str, Any]) -> dict[str, tuple[Decimal, Decimal]]:
    if report.get('code') != 0 or str(report.get('page_context', {}).get('cash_based')).lower() != 'false':
        raise ValueError('Successful accrual trial balance required')
    names = {n for tax in ('CGST', 'SGST', 'IGST', 'CESS') for n in (f'Input {tax}', f'Output {tax}', f'Cash Ledger : {tax} Tax')}
    found = {}

    def visit(nodes):
        for node in nodes:
            name = node.get('name')
            if name in names:
                if name in found:
                    raise ValueError('Ambiguous GST account: ' + name)
                values = node.get('values', [node])
                if not isinstance(values, list) or len(values) != 1:
                    raise ValueError('Single-period trial balance required')
                amounts = [to_finite_decimal(values[0].get(k)) for k in ('net_debit', 'net_credit')]
                if any(v is None for v in amounts):
                    raise ValueError('Missing or invalid GST debit/credit: ' + name)
                found[name] = tuple(amounts)
            visit(node.get('accounts', node.get('account_transactions', [])))

    root = report.get('trialbalance')
    if not isinstance(root, (dict, list)):
        raise ValueError('Trial balance rows missing')
    visit([root] if isinstance(root, dict) else root)
    if names - found.keys():
        raise ValueError('Missing GST accounts: ' + ', '.join(sorted(names - found.keys())))
    return found


def check_monthly_gst(current: Mapping[str, Any], following: Mapping[str, Any]) -> list[MonthlyGSTCheck]:
    current_context, next_context = current.get('page_context', {}), following.get('page_context', {})
    start = date.fromisoformat(current_context['from_date'])
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    if (current_context.get('from_date'), current_context.get('to_date')) != month_bounds(start.year, start.month) or (next_context.get('from_date'), next_context.get('to_date')) != month_bounds(year, month):
        raise ValueError('Consecutive complete calendar months required')
    now, later = gst_movements(current), gst_movements(following)
    rows = []
    for tax in ('CGST', 'SGST', 'IGST', 'CESS'):
        debit, credit = now[f'Output {tax}']; output = credit - debit
        debit, credit = now[f'Input {tax}']; input_tax = debit - credit
        cash = later[f'Cash Ledger : {tax} Tax'][0]
        net = output - input_tax
        rows.append(MonthlyGSTCheck(tax, output, input_tax, net, cash, cash - net))
    return rows
