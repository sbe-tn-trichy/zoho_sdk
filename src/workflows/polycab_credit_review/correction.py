"""Reviewed correction payloads and checkpointed Books writes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Callable

from zoho.helpers.references import update_reference_lines
from .evidence import read_record
from .models import (CreditAudit, CreditCorrectionError, CreditCorrectionPlan,
                     CreditCorrectionResult, RmaCreditPolicy)
from .rules import evaluate, money, reference_pairs

_LABELS = ('VC#', 'CN#', 'SUPPLIER_CN#', 'RSO#', 'INV#', 'JNL#', 'CP#', 'TOTAL_INR',
           'INVOICE_APPLIED_INR', 'ROUNDING_INV#', 'ROUNDING_APPLIED_INR', 'UNAPPLIED_INR')
_RESOURCES = {'vc': ('vendor_credits', 'vendor_credit', 'vendor_credit_id'),
              'journal': ('journals', 'journal', 'journal_id'),
              'payment': ('customer_payments', 'payment', 'payment_id')}


def _records(audit: CreditAudit) -> dict[str, dict[str, Any]]:
    if audit.journal is None or audit.payment is None:
        raise ValueError('A correction requires a journal and payment')
    return {'vc': audit.credit, 'journal': audit.journal, 'payment': audit.payment}


def _financial_state(record: dict[str, Any], kind: str) -> dict[str, Any]:
    """Capture financial fields; the permitted changes are item/account/narration only."""
    fields = ['date', 'journal_date', 'vendor_credit_number', 'entry_number', 'payment_number',
              'vendor_id', 'customer_id', 'location_id', 'currency_id', 'exchange_rate', 'status',
              'payment_status', 'reference_number', 'total', 'amount', 'balance', 'unused_amount',
              'account_id', 'total_credits_used', 'total_refunded_amount', 'adjustment',
              'discount_total', 'taxes', 'documents', 'invoices', 'bills_credited']
    state = {key: deepcopy(record.get(key)) for key in fields}
    state['line_items'] = [{key: deepcopy(line.get(key)) for key in
                            ('line_item_id', 'line_id', 'quantity', 'rate', 'amount',
                             'debit_or_credit', 'tax_id', 'location_id', 'discount',
                             'line_item_taxes', 'line_item_tds', 'item_total')}
                           for line in record.get('line_items', [])]
    if kind == 'vc':
        state['other_custom_fields'] = {x['customfield_id']: deepcopy(x.get('value'))
                                       for x in record.get('custom_fields', [])}
    return state


def _concurrency_state(record: dict[str, Any], kind: str) -> dict[str, Any]:
    state = _financial_state(record, kind)
    state.update(notes=record.get('notes'), description=record.get('description'),
                 modified=record.get('last_modified_time', record.get('updated_time')),
                 lines=[(x.get('item_id'), x.get('account_id'), x.get('description'))
                        for x in record.get('line_items', [])])
    return state


def build_credit_correction_plan(audit: CreditAudit, policy: RmaCreditPolicy) -> CreditCorrectionPlan:
    """Build a plan only from supported, uniquely linked, PDF-supported return credits."""
    audit = deepcopy(audit)
    checked = evaluate(replace(audit, findings=[]), policy)
    # Download/parser failures cannot disappear during reevaluation.
    checked.findings.extend(f for f in audit.findings if f.code == 'pdf_error' or f.code.startswith('shared_'))
    if not checked.correction_allowed:
        messages = [f.message for f in checked.findings if f.blocking]
        raise ValueError('Credit cannot be corrected automatically: ' + '; '.join(messages or ['not an RMA credit']))
    credit, journal, payment = checked.credit, checked.journal, checked.payment
    assert journal is not None and payment is not None
    pairs = reference_pairs(checked)
    pairs += [('SUPPLIER_CN#', m.printed_number) for m in checked.memos if m.printed_number]
    pairs.append(('TOTAL_INR', f"{money(credit['total']):.2f}"))
    invoice = checked.memos[0].invoice_number
    applied = sum(money(x['amount_applied']) for x in payment['invoices'] if x['invoice_number'] == invoice)
    pairs.append(('INVOICE_APPLIED_INR', f'{applied:.2f}'))
    for row in payment['invoices']:
        if row['invoice_number'] != invoice:
            pairs += [('ROUNDING_INV#', row['invoice_number']),
                      ('ROUNDING_APPLIED_INR', f"{money(row['amount_applied']):.2f}")]
    pairs.append(('UNAPPLIED_INR', f"{money(payment['unused_amount']):.2f}"))
    lines = []
    remaining = list(checked.memos)
    for line in credit['line_items']:
        memo = next(m for m in remaining if m.amount == money(line['rate']))
        remaining.remove(memo)
        row = {key: line[key] for key in ('line_item_id', 'quantity', 'rate', 'item_order', 'tax_id', 'location_id') if key in line}
        row.update(item_id=policy.rma_item_id, account_id=policy.rma_account_id,
                   description=update_reference_lines(line.get('description', ''),
                       [('CN#', memo.supplier_number)] + [(k, v) for k, v in reference_pairs(checked) if k not in ('VC#', 'CN#')],
                       managed_labels=_LABELS))
        lines.append(row)
    custom_fields = [{'customfield_id': x['customfield_id'],
                      'value': True if x.get('api_name') == policy.against_invoice_field else x['value']}
                     for x in credit['custom_fields']]
    jlines = []
    for line in journal['line_items']:
        row = {key: line[key] for key in ('line_id', 'debit_or_credit', 'amount', 'tax_id', 'location_id', 'account_id') if key in line}
        if row['debit_or_credit'] == 'debit':
            row['account_id'] = policy.rma_account_id
        row['description'] = update_reference_lines(line.get('description', ''), reference_pairs(checked), managed_labels=_LABELS)
        jlines.append(row)
    payloads = {
        'vc': {'line_items': lines, 'custom_fields': custom_fields,
               'notes': update_reference_lines(credit.get('notes', ''), pairs, managed_labels=_LABELS)},
        'journal': {'journal_date': journal['journal_date'], 'journal_type': journal['journal_type'],
                    'location_id': journal['location_id'], 'line_items': jlines,
                    'notes': update_reference_lines(journal.get('notes', ''), pairs, managed_labels=_LABELS)},
        'payment': {'description': update_reference_lines(payment.get('description', ''), pairs, managed_labels=_LABELS)},
    }
    return CreditCorrectionPlan(policy, checked, payloads)


def _already_matches(record: dict[str, Any], payload: dict[str, Any]) -> bool:
    for key, value in payload.items():
        if key in ('line_items', 'custom_fields'):
            observed = record.get(key, [])
            if len(observed) != len(value) or any(any(old.get(k) != v for k, v in expected.items()) for old, expected in zip(observed, value)):
                return False
        elif record.get(key) != value:
            return False
    return True


def execute_credit_correction(
    books_client: Any, plan: CreditCorrectionPlan, *, dry_run: bool = True,
    checkpoint: Callable[[CreditCorrectionResult], None] | None = None,
) -> CreditCorrectionResult:
    """Preflight all three records, checkpoint each submission, reread every write.

    On any failure stop with completed/pending operations. No blind retry or API
    rollback: an uncertain submission requires live-state reconciliation first.
    """
    rebuilt = build_credit_correction_plan(plan.audit, plan.policy)
    if rebuilt.payloads != plan.payloads:
        raise ValueError('Correction payload was changed after planning')
    result = CreditCorrectionResult(plan.audit.credit['vendor_credit_id'], dry_run)
    if dry_run:
        return result
    if checkpoint is None:
        raise ValueError('Live correction requires a checkpoint callback')
    before = _records(plan.audit)
    current = {}
    for name, (resource_name, key, id_key) in _RESOURCES.items():
        current[name] = read_record(getattr(books_client, resource_name), before[name][id_key], key, id_key)
        if _concurrency_state(current[name], name) != _concurrency_state(before[name], name):
            raise ValueError(f'{name} changed since planning; audit and plan again')
    # Confirm the PDF invoice is live, belongs to this customer/location, and supports allocations.
    for allocation in current['payment']['invoices']:
        invoice = read_record(books_client.invoices, allocation['invoice_id'], 'invoice', 'invoice_id')
        if (invoice.get('customer_id') != plan.policy.customer_id
                or invoice.get('location_id') != current['vc'].get('location_id')
                or invoice.get('invoice_number') != allocation['invoice_number']
                or money(invoice['total']) < money(allocation['amount_applied'])):
            raise ValueError('Payment invoice identity/allocation preflight failed')
    result.status = 'submitting'
    checkpoint(result)
    try:
        for name, (resource_name, key, id_key) in _RESOURCES.items():
            resource = getattr(books_client, resource_name)
            latest = read_record(resource, before[name][id_key], key, id_key)
            if _concurrency_state(latest, name) != _concurrency_state(current[name], name):
                raise ValueError(f'{name} changed during execution')
            if not _already_matches(latest, plan.payloads[name]):
                result.pending = name
                checkpoint(result)  # Persist intent before an uncertain HTTP call.
                response = resource.update(latest[id_key], deepcopy(plan.payloads[name]))
                if response.get('code') != 0:
                    raise ValueError(f'{name} update was not acknowledged')
            after = read_record(resource, latest[id_key], key, id_key)
            expected = _financial_state(before[name], name)
            if name == 'vc':
                field_id = next(x['customfield_id'] for x in before[name]['custom_fields'] if x.get('api_name') == plan.policy.against_invoice_field)
                expected['other_custom_fields'][field_id] = True
            if _financial_state(after, name) != expected or not _already_matches(after, plan.payloads[name]):
                raise ValueError(f'{name} read-back verification failed')
            result.after[name] = after
            result.completed.append(name)
            result.pending = ''
            checkpoint(result)
        result.status = 'verified'
        checkpoint(result)
        return result
    except Exception as exc:
        result.status, result.error = 'failed', str(exc)
        checkpoint(result)
        raise CreditCorrectionError(str(exc), result) from exc
