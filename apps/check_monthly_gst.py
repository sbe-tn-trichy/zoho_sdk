"""Compare each GST month with next-month cash tax debits."""
import argparse
from decimal import Decimal
from datetime import datetime
from pathlib import Path
try:
    from . import _bootstrap
except ImportError:
    import _bootstrap
from workflows.core.auth import get_books_client
from workflows.core.checkpoint import write_atomic_json, atomic_text_writer
from workflows.audited_financials.reports import fetch_trial_balance_for_firm
from workflows.gst_monthly import month_bounds, check_monthly_gst


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start-month', default='2024-04')
    p.add_argument('--end-month', default='2025-03')
    p.add_argument('--firm', default='BD')
    p.add_argument('--output', type=Path, default=Path('output/monthly-gst'))
    args = p.parse_args()
    start, end = [datetime.strptime(v, '%Y-%m') for v in (args.start_month, args.end_month)]
    if start > end: raise ValueError('Start month follows end month')
    api = get_books_client(); snapshots = {}; periods = []; y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        periods.append((y, m)); y, m = (y+1, 1) if m == 12 else (y, m+1)
    for y, m in periods + [(y, m)]:
        key = f'{y}-{m:02d}'; first, last = month_bounds(y, m)
        report = fetch_trial_balance_for_firm(api, from_date=first, to_date=last, firm=args.firm, show_rows='all')
        context = report.get('page_context', {})
        if context.get('from_date') != first or context.get('to_date') != last: raise ValueError('Report dates do not match')
        snapshots[key] = report
        write_atomic_json(args.output/f'{key}.json', report)
        print('Fetched', key, flush=True)
    lines = ['# Monthly GST versus following-month cash ledger', '', f'Firm: {args.firm}; created {datetime.now().astimezone().isoformat(timespec="seconds")}', '',
        'GST movement = output credits minus debits, less input debits minus credits. Payment proxy = next-month Cash Ledger Tax gross debits; interest and late fees excluded. Cross-head ITC, carry-forward credit, adjustments and late payments can explain differences. Cash debits are not independently verified bank payments.', '',
        '| GST month | Payment month | Tax | Output | Input | Output − Input | Cash tax debits | Difference | Result |',
        '|---|---|---|---:|---:|---:|---:|---:|---|']
    mismatches = 0
    for y,m in periods:
        ny,nm = (y+1,1) if m==12 else (y,m+1)
        key,nkey = f'{y}-{m:02d}',f'{ny}-{nm:02d}'
        rows = check_monthly_gst(snapshots[key], snapshots[nkey])
        for c in rows:
            bad = abs(c.difference)>Decimal('.01'); mismatches += bad
            lines.append(f'| {key} | {nkey} | {c.tax} | {c.output:,.2f} | {c.input:,.2f} | {c.net:,.2f} | {c.next_month_cash_debits:,.2f} | {c.difference:,.2f} | {"Review" if bad else "Match"} |')
        net = sum(c.net for c in rows); cash = sum(c.next_month_cash_debits for c in rows)
        lines.append(f'| {key} | {nkey} | **Total** | | | {net:,.2f} | {cash:,.2f} | {cash-net:,.2f} | {"Review" if abs(cash-net)>Decimal(".01") else "Match"} |')
    with atomic_text_writer(args.output/'report.md') as f: f.write('\n'.join(lines)+'\n')
    print(args.output/'report.md'); print(mismatches, 'tax-head differences require review')


if __name__ == '__main__': main()
