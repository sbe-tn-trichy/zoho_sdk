#!/usr/bin/env python3
"""Create a matched invoice/bill pair for explicitly selected replenishment items."""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

try:
    from . import _bootstrap
except ImportError:
    import _bootstrap

from workflows.core.auth import get_books_client, get_inventory_client
from workflows.stock_transfer import (
    build_plan, build_payloads, line_total, split_plan, transaction_dates,
    validate_series_start_date, validate_stock,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--items-csv', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--customer-id', required=True)
    parser.add_argument('--vendor-id', required=True)
    parser.add_argument('--purchase-account-id', action='append', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--invoice-number-prefix', required=True,
                        help='Exact prefix identifying the source invoice number series')
    parser.add_argument('--starting-date', type=date.fromisoformat, required=True)
    parser.add_argument('--ending-date', type=date.fromisoformat, required=True)
    parser.add_argument('--maximum-invoice-total', type=Decimal, required=True,
                        help='Maximum final invoice value, including tax')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resume', action='store_true',
                        help='Resume the journaled invoice/bill pair after verification')
    args = parser.parse_args()
    if not args.reference or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.reference):
        parser.error('Reference must use letters, digits, hyphens or underscores')
    output = Path('output/stock_transfer') / args.reference
    output.mkdir(parents=True, exist_ok=True)
    journal = output / 'execution.json'
    if journal.exists() and not args.resume:
        raise RuntimeError(f'Execution already attempted; inspect {journal} before recovery. Do not recreate the pair.')
    if args.resume and not journal.exists():
        raise RuntimeError(f'No execution journal exists to resume at {journal}')
    resume_state = json.loads(journal.read_text()) if args.resume else None
    if resume_state and resume_state.get('reference') != args.reference:
        raise ValueError('Execution journal reference does not match --reference')
    books, inventory = get_books_client(), get_inventory_client()

    def fetch_details(item_ids):
        details = inventory.items.get_details(item_ids)
        for index, item in enumerate(details, 1):
            loc = next(row for row in item['locations'] if row['location_id'] == args.source)
            if loc.get('is_storage_location_enabled'):
                time.sleep(1.0)
                for attempt in range(3):
                    try:
                        item['transfer_bins'] = inventory.items.list_bins(item['item_id'], args.source)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2 ** attempt)
            if index % 20 == 0:
                print(f'Checked bins for {index}/{len(details)} items', flush=True)
        # Refresh location balances after the paced bin reads.
        fresh = {item['item_id']: item for item in inventory.items.get_details(item_ids)}
        for item in details:
            item['locations'] = fresh[item['item_id']]['locations']
        return details
    with args.items_csv.open() as handle:
        ids = [row['item_id'] for row in csv.DictReader(handle)]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate CSV item IDs')
    details = fetch_details(ids)
    lines = build_plan(details, args.source, args.destination, args.purchase_account_id)
    documents = split_plan(lines, args.maximum_invoice_total)
    dates = transaction_dates(args.starting_date, args.ending_date)
    existing_invoices = books.invoices.list_all(params={
        'location_id': args.source, 'sort_column': 'date', 'sort_order': 'D',
    })
    validate_series_start_date(args.starting_date, existing_invoices, args.invoice_number_prefix)
    locations = {row['location_id']: row for row in books.locations.list_all()}
    customer = books.contacts.get(args.customer_id)['contact']
    vendor = books.contacts.get(args.vendor_id)['contact']
    payload_sets = []
    for index, document_lines in enumerate(documents, 1):
        reference = f'{args.reference}-{index:03d}'
        payload_sets.append(build_payloads(
            document_lines, locations[args.source], locations[args.destination], customer, vendor,
            dates[(index - 1) % len(dates)], reference,
        ))
    resumed_document = int(resume_state.get('document') or 0) if resume_state else 0
    for resource in (books.invoices, books.bills):
        for index in range(1, len(documents) + 1):
            reference = f'{args.reference}-{index:03d}'
            existing = resource.list_all(params={'reference_number': reference})
            if any(row.get('reference_number') == reference for row in existing) and index > resumed_document:
                raise ValueError(f'A transaction already exists with transfer reference {reference}')
    (output / 'plan.json').write_text(json.dumps({
        'lines': [asdict(line) for line in lines], 'documents': payload_sets,
    }, default=str, indent=2))
    print(json.dumps({'items': len(lines), 'quantity': str(sum(line.quantity for line in lines)),
                      'documents': len(documents),
                      'largest_estimated_total': str(max(sum(line_total(line) for line in doc) for doc in documents)),
                      'markup_percentage': '3', 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    state = resume_state or {'reference': args.reference, 'stage': 'preflight'}

    def checkpoint(stage, **data):
        state.update(stage=stage, **data)
        journal.write_text(json.dumps(state, default=str, indent=2))

    def verify_document(doc, kind, expected, expected_lines):
        if doc['location_id'] != expected['location_id'] or doc['gst_no'] != expected['gst_no']:
            raise ValueError('Created document location/GSTIN mismatch')
        actual = {str(row['item_id']): row for row in doc['line_items']}
        if len(actual) != len(expected_lines) or len(doc['line_items']) != len(expected_lines):
            raise ValueError('Created document item count mismatch')
        for row in expected['line_items']:
            found = actual[row['item_id']]
            for key in ('quantity', 'rate', 'tax_id', 'location_id', 'account_id'):
                if str(found.get(key)) != str(row[key]) and found.get(key) != row[key]:
                    raise ValueError(f'Created {kind} {key} mismatch')

    def align_bill_total(invoice, bill):
        difference = Decimal(str(invoice['total'])) - Decimal(str(bill['total']))
        if difference:
            if abs(difference) > Decimal('1.00'):
                raise ValueError('Paired totals differ by more than the permitted rounding adjustment')
            adjustment = Decimal(str(bill.get('adjustment') or 0)) + difference
            bill = books.bills.update(bill['bill_id'], {
                'adjustment': float(adjustment),
                'adjustment_description': 'Rounding adjustment to match paired invoice',
                'is_draft': True,
            })['bill']
        if Decimal(str(invoice['total'])) != Decimal(str(bill['total'])):
            raise ValueError('Bill rounding adjustment did not match the invoice total')
        return bill

    validate_stock(lines, details, args.source, args.destination)
    completed = list(state.get('completed') or [])
    if resume_state:
        if state.get('stage') not in {'bill_created', 'bill_aligned'} or not resumed_document:
            raise RuntimeError('Automatic resume requires a journal stopped after creating a bill')
        document_lines, payloads = documents[resumed_document - 1], payload_sets[resumed_document - 1]
        invoice = books.invoices.get(state['invoice']['invoice_id'])['invoice']
        bill = books.bills.get(state['bill']['bill_id'])['bill']
        verify_document(invoice, 'invoice', payloads['invoice'], document_lines)
        verify_document(bill, 'bill', payloads['bill'], document_lines)
        if invoice['status'] != 'draft' or bill['status'] != 'draft':
            raise ValueError('Resume requires the existing invoice and bill to remain drafts')
        bill = align_bill_total(invoice, bill)
        completed.append({'invoice_id': invoice['invoice_id'], 'invoice_number': invoice['invoice_number'],
                          'bill_id': bill['bill_id'], 'total': invoice['total'], 'date': invoice['date']})
        checkpoint('pair_recovered', document=resumed_document, completed=completed, invoice=invoice, bill=bill)
    for index, (document_lines, payloads) in enumerate(zip(documents, payload_sets), 1):
        if index <= resumed_document:
            continue
        checkpoint('creating_invoice', document=index, completed=completed)
        invoice = books.invoices.create(payloads['invoice'])['invoice']
        checkpoint('invoice_created', document=index, completed=completed, invoice=invoice)
        verify_document(invoice, 'invoice', payloads['invoice'], document_lines)
        if invoice['status'] != 'draft' or Decimal(str(invoice['total'])) > args.maximum_invoice_total:
            raise ValueError('Expected a draft invoice within the maximum threshold')
        payloads['bill']['bill_number'] = invoice['invoice_number']
        checkpoint('creating_bill', document=index, completed=completed, invoice=invoice)
        bill = books.bills.create(payloads['bill'])['bill']
        checkpoint('bill_created', document=index, completed=completed, invoice=invoice, bill=bill)
        verify_document(bill, 'bill', payloads['bill'], document_lines)
        if bill['status'] != 'draft':
            raise ValueError('Expected a draft bill')
        bill = align_bill_total(invoice, bill)
        checkpoint('bill_aligned', document=index, completed=completed, invoice=invoice, bill=bill)
        completed.append({'invoice_id': invoice['invoice_id'], 'invoice_number': invoice['invoice_number'],
                          'bill_id': bill['bill_id'], 'total': invoice['total'], 'date': invoice['date']})
    # Recheck the aggregate stock once after all drafts, before any document is posted.
    validate_stock(lines, fetch_details([line.item_id for line in lines]), args.source, args.destination)
    for entry in completed:
        checkpoint('posting', completed=completed, current=entry)
        books.invoices.mark_as_sent(entry['invoice_id'])
        books.bills.mark_as_open(entry['bill_id'])
    after = inventory.items.get_details([line.item_id for line in lines])
    (output / 'stock_after.json').write_text(json.dumps(after, indent=2))
    negative = [i['item_id'] for i in after for loc in i['locations']
                if loc['location_id'] == args.source and float(loc['location_stock_on_hand']) < 0]
    checkpoint('complete' if not negative else 'stock_verification_failed', completed=completed, negative_source_items=negative)
    if negative:
        raise ValueError('Source stock verification failed; inspect the execution journal')
    print(json.dumps({'completed': completed}), flush=True)


if __name__ == '__main__':
    main()
