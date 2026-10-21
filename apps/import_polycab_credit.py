#!/usr/bin/env python3
"""Preview or import one Polycab credit memo, including RSO settlement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config, get_config
from workflows.polycab_credit_memos import CreditImportPolicy, import_credit_pdf
from zoho.security import resolve_output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf_path', type=Path)
    for name, default in (
        ('vendor', Config.POLYCAB_VENDOR_ID), ('location', Config.EXPECTED_LOCATION_ID),
        ('scheme-item', Config.ZOHO_SCHEME_CN_ITEM_ID),
        ('scheme-account', get_config('POLYCAB_SCHEME_ACCOUNT_ID', '')),
        ('rma-account', get_config('POLYCAB_RMA_ACCOUNT_ID', '')),
        ('clearing-account', get_config('POLYCAB_CLEARING_ACCOUNT_ID', '')),
    ):
        parser.add_argument('--' + name + '-id', default=default)
    parser.add_argument('--checkpoint', default='output/polycab_credit_import/checkpoint.json')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        policy = CreditImportPolicy(args.vendor_id, args.location_id, args.scheme_item_id,
                                    args.scheme_account_id, args.rma_account_id, args.clearing_account_id)
        result = import_credit_pdf(get_books_client(), args.pdf_path, policy=policy,
            checkpoint_path=Path(resolve_output_path(args.checkpoint)), apply=args.apply)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')
    summary = {key: result[key] for key in ('status', 'credit_payload', 'journal_plan', 'payment_plan') if key in result}
    summary['records'] = {name: {key: record[key] for key in
        ('vendor_credit_id', 'vendor_credit_number', 'journal_id', 'entry_number', 'payment_id', 'payment_number') if key in record}
        for name, record in result['records'].items()}
    if args.apply:
        summary['checkpoint'] = str(Path(args.checkpoint).resolve())
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
