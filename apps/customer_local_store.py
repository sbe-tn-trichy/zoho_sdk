#!/usr/bin/env python3
"""Download Books customers or stage/review local changes; no cloud writes."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401
from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.customer_table import customer_json, compact_customer_columns
from workflows.customer_local_store import open_store, sync_customers, stage_mobile_plan, export_pending


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['sync', 'stage-mobile', 'export', 'migrate', 'json', 'csv', 'compact'])
    parser.add_argument('--db', type=Path, default=Path('output/customer_cleanup/customers.sqlite3'))
    parser.add_argument('--plan', type=Path, default=Path('output/customer_cleanup/mobile_empty_preparation/plan.json'))
    parser.add_argument('--output', type=Path, default=Path('output/customer_cleanup/pending_changes.json'))
    parser.add_argument('--contact-id', help='Required for the json action')
    args = parser.parse_args()
    if args.action == 'json' and not args.contact_id:
        parser.error('--contact-id is required for json')
    db = open_store(args.db, organization_id=str(Config.ORG_ID))
    try:
        if args.action == 'sync':
            result = sync_customers(db, get_books_client())
        elif args.action == 'stage-mobile':
            result = stage_mobile_plan(db, args.plan)
        elif args.action == 'compact':
            with db:
                result = compact_customer_columns(db)
        elif args.action == 'migrate':
            result = {'customers': db.execute('SELECT count(*) FROM customers').fetchone()[0],
                      'columns': len(db.execute('PRAGMA table_info(customers)').fetchall())}
        elif args.action == 'json':
            result = customer_json(db, args.contact_id)
        elif args.action == 'csv':
            destination = args.db.parent / 'customers_table.csv'
            table = 'customers_full' if db.execute("SELECT 1 FROM sqlite_master WHERE type='view' AND name='customers_full'").fetchone() else 'customers'
            cursor = db.execute(f'SELECT * FROM {table} ORDER BY contact_name,contact_id')
            with destination.open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream)
                writer.writerow([c[0] for c in cursor.description])
                writer.writerows(cursor)
            result = {'csv': str(destination)}
        else:
            result = export_pending(db, args.output)
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == '__main__':
    main()
