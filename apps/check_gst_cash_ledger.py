"""Check GST cash-ledger balances against output minus input GST."""
import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

try:
    from . import _bootstrap
except ImportError:
    import _bootstrap
from workflows.core.auth import get_books_client
from workflows.core.checkpoint import write_atomic_json, atomic_text_writer
from workflows.gst_cash_ledger import check_gst_cash_ledger, fetch_gst_cash_ledger_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-date', default='2024-04-01')
    parser.add_argument('--to-date', default='2025-03-31')
    parser.add_argument('--firm', default='BD')
    parser.add_argument('--saved', type=Path, help='Use a saved balance-sheet JSON; no network')
    parser.add_argument('--tolerance', type=Decimal, default=Decimal('0.01'))
    parser.add_argument('--output', type=Path, default=Path('output/gst-cash-ledger'))
    args = parser.parse_args()
    report = json.loads(args.saved.read_text(encoding='utf-8-sig')) if args.saved else fetch_gst_cash_ledger_report(
        get_books_client(), from_date=args.from_date, to_date=args.to_date, firm=args.firm)
    checks = check_gst_cash_ledger(report, tolerance=args.tolerance)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.saved and args.saved.resolve() in {(args.output/'balancesheet.json').resolve(), (args.output/'report.md').resolve()}:
        raise ValueError('Output must not overwrite saved source')
    write_atomic_json(args.output/'balancesheet.json', report)
    lines = ['# GST cash-ledger mismatch check', '', f'Created: {datetime.now().astimezone().isoformat(timespec="seconds")}', '',
        f'As of {report["page_context"]["to_date"]}; accrual balances. Tolerance ₹{args.tolerance}.', '',
        'Cash Ledger Tax balance = Output GST minus Input GST. Difference = cash ledger minus expected. Interest and late fees excluded. Closing balances are compared; tax payments and set-offs can affect this equality. This check does not establish a filing or posting error.', '',
        '| GST | Cash ledger | Output GST | Input GST | Expected net GST | Difference | Result |',
        '|---|---:|---:|---:|---:|---:|---|']
    for c in checks:
        lines.append(f'| {c.tax} | {c.cash_ledger:,.2f} | {c.output_gst:,.2f} | {c.input_gst:,.2f} | {c.expected:,.2f} | {c.difference:,.2f} | {"MISMATCH" if c.mismatch else "Match"} |')
    with atomic_text_writer(args.output/'report.md') as handle:
        handle.write('\n'.join(lines)+'\n')
    print((args.output/'report.md').resolve())
    print(f'{sum(c.mismatch for c in checks)} of {len(checks)} GST heads mismatch')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
