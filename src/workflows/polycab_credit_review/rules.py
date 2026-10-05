"""Polycab return-credit accounting rules and correction eligibility."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from workflows.core.matching import parse_currency_amount, parse_date
from zoho.helpers.custom_fields import get_custom_field_value
from zoho.helpers.references import format_reference_lines, parse_reference_lines
from .models import CreditAudit, CreditFinding, RmaCreditPolicy


def money(value: Any) -> Decimal:
    amount = parse_currency_amount(value)
    if not amount.is_finite():
        raise ValueError('Financial amounts must be finite')
    return amount


def reference_pairs(audit: CreditAudit) -> list[tuple[str, str]]:
    """One value per line, including repeated supplier-note labels for combined VCs."""
    values = [('VC#', audit.credit['vendor_credit_number'])]
    values += [('CN#', m.supplier_number) for m in audit.memos]
    for label, attr in (('RSO#', 'rso_number'), ('INV#', 'invoice_number')):
        values += [(label, value) for value in dict.fromkeys(getattr(m, attr) for m in audit.memos) if value]
    if audit.journal:
        values.append(('JNL#', audit.journal['entry_number']))
    if audit.payment:
        values.append(('CP#', audit.payment['payment_number']))
    return values


def reference_findings(audit: CreditAudit) -> list[CreditFinding]:
    expected = parse_reference_lines(format_reference_lines(reference_pairs(audit)))
    findings = []
    for name, text in [('vc', audit.credit.get('notes', '')),
                       ('journal', (audit.journal or {}).get('notes', '')),
                       ('payment', (audit.payment or {}).get('description', ''))]:
        observed = parse_reference_lines(text)
        if any(Counter(observed.get(k, [])) != Counter(v) for k, v in expected.items()):
            findings.append(CreditFinding(name + '_references', f'{name} needs labeled reference lines'))
    return findings


def evaluate(audit: CreditAudit, policy: RmaCreditPolicy) -> CreditAudit:
    """Classify findings without creating documents or changing invoice allocations."""
    credit, journal, payment = audit.credit, audit.journal, audit.payment
    def add(code: str, message: str, blocking: bool = False) -> None:
        audit.findings.append(CreditFinding(code, message, blocking))

    if credit.get('vendor_id') != policy.vendor_id:
        add('vendor_identity', 'Credit does not belong to the configured vendor', True)
    if money(credit.get('total')) <= 0 or parse_date(credit.get('date')) is None:
        add('credit_identity', 'Credit requires a positive total and valid date', True)

    documents = credit.get('documents')
    if not isinstance(documents, list) or not documents:
        add('missing_attachment', 'Credit has no readable document list', True)
    else:
        duplicate = [name for name, count in Counter(x.get('file_name') for x in documents).items() if count > 1]
        if duplicate:
            add('duplicate_attachment_names', 'Repeated filenames: ' + ', '.join(str(x) for x in duplicate))
    if not audit.memos:
        add('no_pdf_evidence', 'No parsed supplier-note evidence', True)
        return audit
    if sum((m.amount for m in audit.memos), Decimal('0')) != money(credit['total']):
        add('pdf_amount_mismatch', 'Net distinct PDF amounts differ from Books total', True)
    if any(m.date != parse_date(credit.get('date')) for m in audit.memos):
        add('pdf_date_mismatch', 'PDF date differs from credit date', True)
    if not any(credit['vendor_credit_number'] in (m.supplier_number, m.printed_number) for m in audit.memos):
        add('pdf_identity_mismatch', 'No PDF matches the Books credit number', True)
    if not audit.is_rma:
        if get_custom_field_value(credit, policy.against_invoice_field) in (True, 'true'):
            add('scheme_against_invoice', 'Scheme PDF has no return/customer-invoice evidence; review flag')
        return audit
    if credit.get('status') not in ('open', 'closed', 'partially_used'):
        add('credit_status', 'Draft, void or unsupported credit status requires manual review', True)
    if not credit.get('vendor_credit_id') or not credit.get('location_id'):
        add('credit_scope', 'Credit ID and location are required', True)
    if any(not m.is_return or m.amount <= 0 for m in audit.memos):
        add('mixed_memos', 'Mixed return/scheme/debit notes require manual review', True)
    rso = {m.rso_number for m in audit.memos}
    invoices = {m.invoice_number for m in audit.memos}
    if len(rso) != 1 or '' in rso or len(invoices) != 1 or '' in invoices:
        add('mixed_references', 'Correction requires one explicit RSO and customer invoice', True)
    if any(not number.startswith(('SBE', 'SB', 'BD')) for number in invoices):
        add('supplier_invoice', 'PDF names a supplier bill; customer invoice mapping is unresolved', True)
    lines = credit.get('line_items', [])
    if not lines or any(not x.get('line_item_id') or money(x.get('quantity')) != 1 or money(x.get('rate')) <= 0
                        or x.get('tax_id') or money(x.get('discount', 0)) != 0 for x in lines):
        add('unsupported_credit_lines', 'Correction supports untaxed quantity-one return lines without discounts', True)
    if any(money(credit.get(k, 0)) != 0 for k in ('adjustment', 'discount_total')) or credit.get('taxes'):
        add('unsupported_credit_totals', 'Tax, discount or adjustment requires manual review', True)
    if Counter(money(x.get('rate')) for x in lines) != Counter(m.amount for m in audit.memos):
        add('line_pdf_mismatch', 'Credit lines do not correspond to distinct PDF amounts', True)
    if any(x.get('item_id') != policy.rma_item_id for x in lines):
        add('rma_item', 'Return lines must use the configured RMA item')
    if any(x.get('account_id') != policy.rma_account_id for x in lines):
        add('rma_account', 'Return lines must use the configured RMA account')
    fields = credit.get('custom_fields', [])
    if any(not x.get('customfield_id') or 'value' not in x for x in fields):
        add('custom_field_schema', 'Cannot safely preserve incomplete custom fields', True)
    if not any(x.get('api_name') == policy.against_invoice_field and x.get('customfield_id') for x in fields):
        add('missing_custom_field', 'Against Invoice custom-field ID is unavailable', True)
    if get_custom_field_value(credit, policy.against_invoice_field) not in (True, 'true'):
        add('against_invoice', 'Against Invoice must be true')
    for name, record, link in [('journal', journal, audit.journal_link), ('payment', payment, audit.payment_link)]:
        if record is None:
            add(name + '_missing', f'No unique linked {name}: {link}', True)
        elif link.startswith('inferred'):
            add(name + '_inferred', f'{name} link is inferred; select an explicit ID after review', True)
        if record and record.get('journal_date' if name == 'journal' else 'date') != credit['date']:
            add(name + '_date', f'{name} date differs from credit date', True)
        if record and money(record.get('total' if name == 'journal' else 'amount')) != money(credit['total']):
            add(name + '_amount', f'{name} amount differs from credit total', True)
        if record and record.get('location_id') != credit.get('location_id'):
            add(name + '_location', f'{name} location differs from credit', True)
    if journal:
        if not journal.get('journal_id') or not journal.get('entry_number'):
            add('journal_identity', 'Journal ID and number are required', True)
        jlines = journal.get('line_items', [])
        debit = [x for x in jlines if x.get('debit_or_credit') == 'debit']
        credit_lines = [x for x in jlines if x.get('debit_or_credit') == 'credit']
        if (journal.get('status') != 'published' or len(debit) != 1 or len(credit_lines) != 1
                or len(jlines) != 2 or any(not x.get('line_id') or x.get('tax_id') or money(x['amount']) != money(credit['total']) for x in jlines)
                or credit_lines[0].get('account_id') != policy.clearing_account_id):
            add('journal_shape', 'Require published untaxed two-line journal crediting the clearing account', True)
        elif debit[0].get('account_id') != policy.rma_account_id:
            if debit[0].get('account_id') not in {x.get('account_id') for x in lines}:
                add('journal_unrelated_debit', 'Journal debit does not match the credit expense account', True)
            else:
                add('journal_account', 'Journal debit must use the configured RMA account')
    if payment:
        if not payment.get('payment_id') or not payment.get('payment_number'):
            add('payment_number', 'Payment ID and number are required', True)
        if payment.get('customer_id') != policy.customer_id or payment.get('account_id') != policy.clearing_account_id:
            add('payment_identity', 'Payment must belong to the configured customer and clearing account', True)
        allocated = sum((money(x['amount_applied']) for x in payment.get('invoices', []) if x.get('invoice_number') in invoices), Decimal('0'))
        delta = money(credit['total']) - allocated
        if delta != 0:
            if allocated > 0 and 0 <= delta <= policy.rounding_tolerance:
                add('rounding', f'Preserve and document rounding difference {delta:.2f}; do not move allocations')
            else:
                add('payment_invoice', 'Payment is not applied to the PDF invoice within rounding tolerance', True)
        if any(money(x['amount_applied']) < 0 for x in payment.get('invoices', [])) or money(payment.get('unused_amount')) < 0:
            add('payment_allocations', 'Invalid negative allocation or unused amount', True)
        applied = sum((money(x['amount_applied']) for x in payment.get('invoices', [])), Decimal('0'))
        if applied + money(payment.get('unused_amount')) != money(payment['amount']):
            add('payment_reconciliation', 'Payment allocations and unused amount do not reconcile', True)
    audit.findings.extend(reference_findings(audit))
    return audit


def flag_shared_links(audits: list[CreditAudit]) -> list[CreditAudit]:
    """A journal/payment shared by separate selected credits requires manual review."""
    for kind in ('journal', 'payment'):
        linked: dict[str, list[CreditAudit]] = {}
        for audit in audits:
            record = getattr(audit, kind)
            if audit.is_rma and record:
                linked.setdefault(record[kind + '_id'], []).append(audit)
        for group in linked.values():
            if len(group) > 1:
                for audit in group:
                    audit.findings.append(CreditFinding('shared_' + kind,
                        f'{kind} is shared by multiple selected vendor credits', True))
    return audits
