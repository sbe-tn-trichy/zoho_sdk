"""Checkpointed supplier-credit import and RSO customer-invoice settlement."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflows.core.checkpoint import write_atomic_json
from workflows.core.matching import parse_currency_amount
from workflows.polycab_credit_review.pdf import read_credit_memo_pdf
from zoho.helpers.records import get_verified_record
from .processor import upload_vendor_credit_attachment


@dataclass(frozen=True)
class CreditImportPolicy:
    vendor_id: str
    location_id: str
    scheme_item_id: str
    scheme_account_id: str
    rma_account_id: str
    clearing_account_id: str
    rma_item_id: str = '1094368000028456138'

    def __post_init__(self) -> None:
        if any(not value.isdigit() for value in vars(self).values()):
            raise ValueError('Import policy requires explicit numeric IDs')


def _verify_payload(record: Any, expected: Any, path: str = 'record') -> None:
    """Check all submitted fields, allowing only additional server fields."""
    if isinstance(expected, dict):
        if not isinstance(record, dict):
            raise ValueError(f'{path} read-back is not a record')
        for key, value in expected.items():
            _verify_payload(record.get(key), value, path + '.' + key)
    elif isinstance(expected, list):
        if not isinstance(record, list) or len(record) != len(expected):
            raise ValueError(f'{path} read-back line count mismatch')
        for index, (actual, wanted) in enumerate(zip(record, expected)):
            _verify_payload(actual, wanted, f'{path}[{index}]')
    elif record != expected:
        raise ValueError(f'{path} read-back mismatch: {record!r} != {expected!r}')


def import_credit_pdf(books: Any, pdf_path: Path, *, policy: CreditImportPolicy,
                      checkpoint_path: Path, apply: bool = False) -> dict[str, Any]:
    """Preview by default; stop on existing credits or uncertain prior submissions.

    A checkpoint is never automatically resumed. Inspect live records before
    recovery; Books cannot atomically create the three accounting records.
    """
    if checkpoint_path.exists():
        raise ValueError(f'Checkpoint already exists; review before retry: {checkpoint_path}')
    memo = read_credit_memo_pdf(pdf_path)
    if memo.amount <= 0:
        raise ValueError('Only positive supplier credit notes can be imported')
    is_rso = memo.is_return
    if is_rso and (not memo.rso_number or not memo.invoice_number):
        raise ValueError('RSO credit requires explicit RSO and customer invoice numbers')
    vendor = get_verified_record(books.contacts, policy.vendor_id, 'contact', 'contact_id')
    if vendor.get('contact_type') != 'vendor' or vendor.get('status') != 'active':
        raise ValueError('Configured vendor is not active')
    expected_accounts = [(policy.rma_account_id, 'RMA Expense'),
                         (policy.clearing_account_id, 'Vendor To Customer')] if is_rso else [(policy.scheme_account_id, 'Polycab Kitty')]
    for identifier, name in expected_accounts:
        account = get_verified_record(books.chart_of_accounts, identifier, 'chart_of_account', 'account_id')
        if account.get('account_name', '').casefold() != name.casefold() or not account.get('is_active'):
            raise ValueError(f'Configured account must be active {name}')
        if identifier == policy.clearing_account_id and account.get('account_type') != 'bank':
            raise ValueError('Vendor To Customer clearing account must be a bank')
    existing = books.vendor_credits.list_all(params={'vendor_id': policy.vendor_id}, resource_key='vendor_credits')
    if any(str(x.get('vendor_id')) == policy.vendor_id and
           str(x.get('vendor_credit_number')) == memo.supplier_number for x in existing):
        raise ValueError('Vendor credit already exists; review its journal/payment instead of recreating')
    invoice = None
    if is_rso:
        candidates = books.invoices.list_all(params={'invoice_number': memo.invoice_number}, resource_key='invoices')
        candidates = [x for x in candidates if x.get('invoice_number') == memo.invoice_number]
        if len(candidates) != 1:
            raise ValueError('Customer invoice number must match exactly one invoice')
        invoice = get_verified_record(books.invoices, candidates[0]['invoice_id'], 'invoice', 'invoice_id')
        if (invoice.get('invoice_number') != memo.invoice_number or
                invoice.get('location_id') != policy.location_id or
                invoice.get('status') in ('draft', 'void') or
                parse_currency_amount(invoice['balance']) < memo.amount):
            raise ValueError('Invoice identity, location, status or available balance is invalid')
    amount = float(memo.amount)
    references = [('SUPPLIER_CN#', memo.supplier_number)]
    if memo.printed_number:
        references.append(('SUPPLIER_PRINTED_CN#', memo.printed_number))
    if is_rso:
        references += [('RSO#', memo.rso_number), ('INV#', memo.invoice_number)]
    references.append(('TOTAL_INR', f'{memo.amount:.2f}'))
    def description() -> str:
        return '\n'.join(f'{key}: {value}' for key, value in references)
    line = {'item_id': policy.rma_item_id if is_rso else policy.scheme_item_id,
            'account_id': policy.rma_account_id if is_rso else policy.scheme_account_id,
            'quantity': 1, 'rate': amount, 'description': description(),
            'gst_treatment_code': 'out_of_scope'}
    credit_payload = {'vendor_id': policy.vendor_id, 'location_id': policy.location_id,
                      'vendor_credit_number': memo.supplier_number, 'date': memo.date.isoformat(),
                      'reference_invoice_type': 'registered', 'line_items': [line]}
    state: dict[str, Any] = {'status': 'preview', 'source': str(pdf_path.resolve()),
                            'policy': vars(policy), 'credit_payload': credit_payload,
                            'invoice': invoice, 'records': {}, 'pending': ''}
    if invoice:
        state['journal_plan'] = {'debit_account_id': policy.rma_account_id,
                                 'credit_account_id': policy.clearing_account_id, 'amount': amount,
                                 'date': memo.date.isoformat(), 'references': description()}
        state['payment_plan'] = {'customer_id': invoice['customer_id'],
                                 'account_id': policy.clearing_account_id, 'amount': amount,
                                 'invoice_id': invoice['invoice_id'], 'invoice_number': memo.invoice_number,
                                 'remaining_invoice_balance': str(parse_currency_amount(invoice['balance']) - memo.amount)}
    if not apply:
        return state
    def checkpoint(pending: str) -> None:
        state['pending'] = pending
        write_atomic_json(checkpoint_path, state)
    def create(name: str, resource: Any, payload: dict[str, Any], key: str, id_key: str) -> dict[str, Any]:
        checkpoint('create_' + name)
        response = resource.create(payload)
        record = response.get(key, response.get('vendorcredit', {}))
        identifier = record.get(id_key)
        if not identifier:
            raise ValueError(f'{name} creation did not return an ID; inspect checkpoint')
        state['records'][name] = record
        checkpoint('verify_' + name)
        record = get_verified_record(resource, identifier, key, id_key)
        _verify_payload(record, payload, name)
        state['records'][name] = record
        checkpoint('')
        return record
    state['status'] = 'submitting'
    checkpoint('preflight')
    try:
        if invoice:
            fresh = get_verified_record(books.invoices, invoice['invoice_id'], 'invoice', 'invoice_id')
            if any(fresh.get(k) != invoice.get(k) for k in ('balance', 'customer_id', 'location_id', 'invoice_number', 'status')):
                raise ValueError('Invoice changed since planning')
        credit = create('credit', books.vendor_credits, credit_payload, 'vendor_credit', 'vendor_credit_id')
        if parse_currency_amount(credit['total']) != memo.amount or credit['vendor_id'] != policy.vendor_id:
            raise ValueError('Vendor credit amount/vendor read-back mismatch')
        references += [('VC#', credit['vendor_credit_number']), ('VC_ID', credit['vendor_credit_id'])]
        if invoice:
            journal_payload = {'journal_date': memo.date.isoformat(), 'journal_type': 'both',
                               'location_id': policy.location_id, 'reference_number': memo.supplier_number,
                               'line_items': [
                                   {'account_id': policy.rma_account_id, 'debit_or_credit': 'debit', 'amount': amount, 'description': description()},
                                   {'account_id': policy.clearing_account_id, 'debit_or_credit': 'credit', 'amount': amount, 'description': description()}]}
            journal = create('journal', books.journals, journal_payload, 'journal', 'journal_id')
            checkpoint('publish_journal')
            if journal.get('status') != 'published':
                books.journals.publish(journal['journal_id'])
            journal = get_verified_record(books.journals, journal['journal_id'], 'journal', 'journal_id')
            _verify_payload(journal, journal_payload, 'journal')
            if journal.get('status') != 'published':
                raise ValueError('Journal publication was not verified')
            references += [('JNL#', str(journal['entry_number'])), ('JNL_ID', journal['journal_id'])]
            payment = create('payment', books.customer_payments,
                {'customer_id': invoice['customer_id'], 'location_id': policy.location_id,
                 'date': memo.date.isoformat(), 'payment_mode': 'banktransfer', 'amount': amount,
                 'account_id': policy.clearing_account_id, 'reference_number': memo.supplier_number,
                 'description': description(), 'invoices': [{'invoice_id': invoice['invoice_id'], 'amount_applied': amount}]},
                'payment', 'payment_id')
            if (payment['customer_id'] != invoice['customer_id'] or payment['account_id'] != policy.clearing_account_id
                    or parse_currency_amount(payment['amount']) != memo.amount
                    or len(payment['invoices']) != 1
                    or payment['invoices'][0]['invoice_id'] != invoice['invoice_id']
                    or parse_currency_amount(payment['invoices'][0]['amount_applied']) != memo.amount):
                raise ValueError('Customer payment allocation read-back mismatch')
            references += [('CP#', str(payment['payment_number'])), ('CP_ID', payment['payment_id'])]
            for name, resource, record, key, id_key, payload in [
                ('journal', books.journals, journal, 'journal', 'journal_id',
                 {**journal_payload, 'line_items': [{**x, 'description': description()} for x in journal_payload['line_items']]}),
                ('payment', books.customer_payments, payment, 'payment', 'payment_id', {'description': description()})]:
                checkpoint('references_' + name)
                resource.update(record[id_key], payload)
                saved = get_verified_record(resource, record[id_key], key, id_key)
                _verify_payload(saved, payload, name)
                state['records'][name] = saved
        checkpoint('references_credit')
        books.vendor_credits.update(credit['vendor_credit_id'], {'line_items': [{**line, 'description': description(), 'line_item_id': credit['line_items'][0]['line_item_id']}]})
        saved = get_verified_record(books.vendor_credits, credit['vendor_credit_id'], 'vendor_credit', 'vendor_credit_id')
        _verify_payload(saved, {'line_items': [{**line, 'description': description()}]}, 'credit')
        if parse_currency_amount(saved['total']) != memo.amount:
            raise ValueError('Vendor credit final read-back failed')
        state['records']['credit'] = saved
        checkpoint('attach_pdf')
        upload_vendor_credit_attachment(books, credit['vendor_credit_id'], str(pdf_path))
        attached = get_verified_record(books.vendor_credits, credit['vendor_credit_id'], 'vendor_credit', 'vendor_credit_id')
        if not attached.get('documents'):
            raise ValueError('Source attachment not verified')
        state['records']['credit'] = attached
        if invoice:
            final_invoice = get_verified_record(books.invoices, invoice['invoice_id'], 'invoice', 'invoice_id')
            if (final_invoice.get('customer_id') != invoice['customer_id']
                    or final_invoice.get('invoice_number') != memo.invoice_number
                    or parse_currency_amount(final_invoice['balance']) != parse_currency_amount(invoice['balance']) - memo.amount):
                raise ValueError('Final invoice balance/identity verification failed')
            state['final_invoice_balance'] = str(parse_currency_amount(final_invoice['balance']))
        state['status'] = 'verified'
        checkpoint('')
        return state
    except Exception as exc:
        state['status'], state['error'] = 'failed', str(exc)
        write_atomic_json(checkpoint_path, state)
        raise
