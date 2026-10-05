#!/usr/bin/env python3
"""Audit Polycab PDFs and preview/apply selected RMA credit corrections."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.checkpoint import write_atomic_json
from workflows.core.config import Config, get_config
from workflows.core.dates import get_fy_date_range
from workflows.polycab_credit_review import (
    CreditCorrectionError, CreditCorrectionResult, RmaCreditPolicy, build_credit_correction_plan,
    execute_credit_correction, review_polycab_vendor_credits,
)
from zoho.security import resolve_output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fy', default='2025-26')
    parser.add_argument('--vendor-id', default=Config.POLYCAB_VENDOR_ID)
    parser.add_argument('--customer-id', default=Config.RSO_CUSTOMER_ID)
    parser.add_argument('--rma-item-id', default=get_config('POLYCAB_RMA_ITEM_ID', ''))
    parser.add_argument('--rma-account-id', default=get_config('POLYCAB_RMA_ACCOUNT_ID', ''))
    parser.add_argument('--clearing-account-id', default=get_config('POLYCAB_CLEARING_ACCOUNT_ID', ''))
    parser.add_argument('--credit', action='append', default=[], help='Exact VC number; repeat for multiple credits')
    parser.add_argument('--journal-id', default='', help='Reviewed explicit link for one selected credit')
    parser.add_argument('--payment-id', default='', help='Reviewed explicit link for one selected credit')
    parser.add_argument('--output-dir', type=Path, default=Path('output/polycab_credit_review'))
    parser.add_argument('--apply', action='store_true', help='Save eligible selected corrections, preserving allocations')
    args = parser.parse_args(argv)
    if args.apply and not args.credit:
        parser.error('--apply requires explicit --credit selections')
    try:
        policy = RmaCreditPolicy(args.vendor_id, args.customer_id, args.rma_item_id,
                                 args.rma_account_id, args.clearing_account_id)
        start, end, _ = get_fy_date_range(args.fy)
    except ValueError as exc:
        parser.error(str(exc))
    output = Path(resolve_output_path(str(args.output_dir)))
    # Unique run files keep earlier audit/checkpoints intact.
    run_id = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    report_path = output / ('review_' + run_id + '.json')
    books = get_books_client()
    audits = review_polycab_vendor_credits(books, policy=policy, from_date=start,
        to_date=end, credit_numbers=args.credit, output_dir=output / run_id,
        journal_id=args.journal_id, payment_id=args.payment_id)
    report = {'policy': asdict(policy), 'from_date': start.isoformat(), 'to_date': end.isoformat(),
              'audits': [asdict(x) for x in audits], 'plans': [], 'results': []}
    plans = []
    for audit in audits:
        print(f"{audit.credit['vendor_credit_number']}: " +
              (', '.join(f.code for f in audit.findings) or 'No findings'))
        if audit.correction_allowed:
            plan = build_credit_correction_plan(audit, policy)
            plans.append(plan)
            report['plans'].append(asdict(plan))
    write_atomic_json(report_path, report)
    print(f'Report: {report_path.resolve()}')
    if args.apply and len(plans) != len(audits):
        print('Some selected credits are ineligible; no updates submitted. Review blocking findings.')
        return 2
    for plan in plans:
        def checkpoint(result: CreditCorrectionResult) -> None:
            write_atomic_json(output / ('checkpoint_' + run_id + '_' + result.vendor_credit_id + '.json'),
                              {'plan': asdict(plan), 'result': asdict(result)})
        try:
            result = execute_credit_correction(books, plan, dry_run=not args.apply, checkpoint=checkpoint)
        except (CreditCorrectionError, ValueError) as exc:
            report['results'].append(asdict(exc.result) if isinstance(exc, CreditCorrectionError)
                                     else {'vendor_credit_id': plan.audit.credit['vendor_credit_id'],
                                           'status': 'preflight_failed', 'error': str(exc)})
            write_atomic_json(report_path, report)
            print(f'Correction stopped: {exc}. Review checkpoint before retrying.')
            return 1
        report['results'].append(asdict(result))
        write_atomic_json(report_path, report)
        print(f"{result.vendor_credit_id}: {result.status}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
