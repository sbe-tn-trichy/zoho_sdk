from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.polycab_credit_review import (
    CreditAudit, CreditCorrectionError, CreditMemoEvidence, RmaCreditPolicy,
    build_credit_correction_plan, execute_credit_correction, parse_credit_memo_text,
    read_credit_memo_pdf, review_polycab_vendor_credits,
)
from workflows.polycab_credit_review.pdf import distinct_memos
from workflows.polycab_credit_review.rules import evaluate
from zoho.helpers import format_reference_lines, parse_reference_lines, update_reference_lines
from zoho.helpers.files import download_books_document


class Resource:
    def __init__(self, records, key, id_key):
        self.records = {row[id_key]: deepcopy(row) for row in records}
        self.key, self.id_key = key, id_key
        self.updates = []
        self.mutate = None

    def list_all(self, **kwargs):
        return deepcopy(list(self.records.values()))

    def get(self, identifier):
        return {self.key: deepcopy(self.records[identifier])}

    def update(self, identifier, payload):
        self.updates.append(deepcopy(payload))
        record = self.records[identifier]
        for key, value in payload.items():
            if key in ('line_items', 'custom_fields'):
                for old, new in zip(record[key], value):
                    old.update(deepcopy(new))
            else:
                record[key] = deepcopy(value)
        if self.mutate:
            self.mutate(record)
        return {'code': 0}


@pytest.fixture
def records():
    policy = RmaCreditPolicy('1', '2', '3', '4', '5')
    day = '2025-04-12'
    lines = [dict(line_item_id=f'l{i}', item_id='old', account_id='old_account',
                  quantity=1, rate=rate, tax_id='', discount=0, item_order=i,
                  location_id='loc', description='', item_total=rate)
             for i, rate in enumerate((13.00, .32), 1)]
    vc = dict(vendor_credit_id='vc', vendor_credit_number='1001', vendor_id='1',
              date=day, total=13.32, location_id='loc', status='closed', reference_number='CP-1',
              line_items=lines, documents=[dict(document_id='d1', file_name='a.pdf'),
                                          dict(document_id='d2', file_name='b.pdf')],
              custom_fields=[dict(customfield_id='flag', api_name='cf_against_invoice', value=False),
                             dict(customfield_id='other', api_name='cf_other', value='keep')],
              notes='Human note', bills_credited=[{'bill_id': 'bill', 'amount': 13.32}], taxes=[], adjustment=0)
    journal = dict(journal_id='j', entry_number='J-1', reference_number='CP-1::1001',
                   journal_date=day, location_id='loc', total=13.32, status='published', journal_type='both',
                   notes='Human journal note', line_items=[dict(line_id='jc', account_id='5', debit_or_credit='credit', amount=13.32, tax_id='', location_id='loc', description=''),
                   dict(line_id='jd', account_id='old_account', debit_or_credit='debit', amount=13.32, tax_id='', location_id='loc', description='')])
    allocations = [dict(invoice_id='i', invoice_number='SBE2526INV-001', amount_applied=13, apply_date=day),
                   dict(invoice_id='i2', invoice_number='SBE2526INV-002', amount_applied=.32, apply_date=day)]
    payment = dict(payment_id='p', payment_number='CP-1', reference_number='1001',
                   customer_id='2', date=day, location_id='loc', amount=13.32, account_id='5',
                   unused_amount=0, invoices=allocations, description='Human payment note')
    memos = tuple(CreditMemoEvidence(str(1000 + i), f'TN/CN{i}', date.fromisoformat(day), Decimal(str(amount)),
                                    '12345', 'SBE2526INV-001', True, f'd{i}')
                  for i, amount in enumerate((13.00, .32), 1))
    audit = evaluate(CreditAudit(vc, memos, journal, payment, [], 'reference', 'reference'), policy)
    invoices = [dict(invoice_id='i', invoice_number='SBE2526INV-001', customer_id='2', location_id='loc', total=13),
                dict(invoice_id='i2', invoice_number='SBE2526INV-002', customer_id='2', location_id='loc', total=10)]
    books = SimpleNamespace(vendor_credits=Resource([vc], 'vendor_credit', 'vendor_credit_id'),
                            journals=Resource([journal], 'journal', 'journal_id'),
                            customer_payments=Resource([payment], 'payment', 'payment_id'),
                            invoices=Resource(invoices, 'invoice', 'invoice_id'))
    return policy, audit, books


def text(number='1001', amount='13.00', rso='12345', invoice='SBE2526INV-001'):
    return f'''POLYCAB INDIA LIMITED
Credit Note
RSO Number : {rso}       E-Way Bill No :
Customer Invoice No. : {invoice}        RCM Applicability :
Customer Invoice Date : 01-APR-2024
AR Invoice Number : {number}
Invoice Date : 12-APR-2025
Credit Note No : TN/CN1
TOTAL {amount}
'''


def test_reference_lines_repeated_keys_idempotence_and_preservation():
    pairs = [('CN#', '1001'), ('CN#', '1002'), ('RSO#', '12345')]
    block = format_reference_lines(pairs)
    assert parse_reference_lines(block)['CN#'] == ['1001', '1002']
    out = update_reference_lines('Human note\nRSO#: old\nOTHER#: keep', pairs, managed_labels=['CN#', 'RSO#'])
    assert 'Human note' in out and 'OTHER#: keep' in out and 'old' not in out
    assert update_reference_lines(out, pairs, managed_labels=['CN#', 'RSO#']) == out
    with pytest.raises(ValueError):
        format_reference_lines([('INV#', 'value\nCP#: injected')])


def test_poppler_text_identity_dates_totals_and_blank_neighbors():
    memo = parse_credit_memo_text(text())
    assert memo.date == date(2025, 4, 12) and memo.amount == Decimal('13.00')
    assert memo.rso_number == '12345'
    blank = parse_credit_memo_text(text(rso='', invoice=''))
    assert not blank.is_return and blank.invoice_number == ''
    debit = parse_credit_memo_text(text().replace('Credit Note\n', 'Debit Note\n'))
    assert debit.amount == Decimal('-13.00')
    with pytest.raises(ValueError, match='valid invoice date'):
        parse_credit_memo_text(text().replace('12-APR-2025', '31-FEB-2025'))


def test_wrapped_scheme_rows_and_conflicting_totals():
    scheme = text(rso='', invoice='').replace('TOTAL 13.00', 'Total Value\n1\nScheme details\n  12.25  1  0  12.25  12.25\n2  details  .75  1  0  .75  0.75\n(Rupees Thirteen only)')
    assert parse_credit_memo_text(scheme).amount == Decimal('13.00')
    with pytest.raises(ValueError, match='conflicting'):
        parse_credit_memo_text(text() + 'TOTAL 20.00\n')


def test_distinct_memos_deduplicate_content_but_reject_contradictions(records):
    memos = records[1].memos
    assert distinct_memos(memos + (replace(memos[0], document_id='copy'),)) == memos
    with pytest.raises(ValueError, match='Conflicting PDFs'):
        distinct_memos(memos + (replace(memos[0], amount=Decimal('14')),))


def test_pdf_reader_uses_poppler_and_checks_pdf_header(tmp_path, monkeypatch):
    path = tmp_path / 'memo.pdf'
    path.write_bytes(b'%PDF fake')
    monkeypatch.setattr('workflows.polycab_credit_review.pdf.shutil.which', lambda name: '/bin/pdftotext')
    run = Mock(return_value=SimpleNamespace(stdout=text()))
    monkeypatch.setattr('workflows.polycab_credit_review.pdf.subprocess.run', run)
    assert read_credit_memo_pdf(path).supplier_number == '1001'
    assert run.call_args.args[0] == ['/bin/pdftotext', '-layout', str(path.resolve()), '-']
    path.write_bytes(b'{"code":0}')
    with pytest.raises(ValueError, match='not a PDF'):
        read_credit_memo_pdf(path)
    monkeypatch.setattr('workflows.polycab_credit_review.pdf.shutil.which', lambda name: None)
    with pytest.raises(RuntimeError, match='Poppler'):
        read_credit_memo_pdf(path)


def test_document_download_streams_closes_and_rejects_endpoint_traversal(tmp_path):
    response = Mock()
    response.iter_content.return_value = [b'%PDF', b' contents']
    books = Mock()
    books.request.return_value = response
    path = tmp_path / 'doc.pdf'
    assert download_books_document(books, 'vendorcredits', '1', '2', str(path)) == str(path)
    response.close.assert_called_once()
    books.request.assert_called_once_with('GET', 'vendorcredits/1/documents/2', stream=True)
    with pytest.raises(ValueError):
        download_books_document(books, 'vendorcredits', '../1', '2', str(path))


def test_plan_preserves_rounding_and_unrelated_notes_fields(records):
    policy, audit, _ = records
    assert audit.correction_allowed
    plan = build_credit_correction_plan(audit, policy)
    payload = plan.payloads['vc']
    assert len(payload['line_items']) == 2
    assert all(x['item_id'] == '3' and x['account_id'] == '4' for x in payload['line_items'])
    assert payload['custom_fields'][1]['value'] == 'keep'
    assert 'RSO#: 12345\nINV#: SBE2526INV-001' in payload['notes']
    assert 'Human note' in payload['notes'] and 'ROUNDING_APPLIED_INR: 0.32' in payload['notes']
    assert set(plan.payloads['payment']) == {'description'}
    assert 'product_type' not in payload['line_items'][0]


@pytest.mark.parametrize('change', ['pdf_total', 'inferred', 'ambiguous', 'tax', 'wrong_customer', 'wrong_clearing', 'large_allocation', 'supplier_invoice', 'unrelated_journal', 'pdf_error', 'void', 'missing_line_id'])
def test_unsafe_cases_block_correction(records, change):
    policy, audit, _ = records
    if change == 'pdf_total':
        audit.memos = (replace(audit.memos[0], amount=Decimal('99')), audit.memos[1])
    elif change == 'inferred':
        audit.payment_link = 'inferred amount/date'
    elif change == 'ambiguous':
        audit.payment, audit.payment_link = None, 'ambiguous reference'
    elif change == 'tax':
        audit.credit['line_items'][0]['tax_id'] = 'tax'
    elif change == 'wrong_customer':
        audit.payment['customer_id'] = 'other'
    elif change == 'wrong_clearing':
        audit.payment['account_id'] = 'other'
    elif change == 'large_allocation':
        audit.payment['invoices'][0]['amount_applied'] = 5
    elif change == 'supplier_invoice':
        audit.memos = tuple(replace(m, invoice_number='TN721BILL') for m in audit.memos)
    elif change == 'unrelated_journal':
        audit.journal['line_items'][1]['account_id'] = 'unrelated'
    elif change == 'void':
        audit.credit['status'] = 'void'
    elif change == 'missing_line_id':
        audit.credit['line_items'][0].pop('line_item_id')
    else:
        from workflows.polycab_credit_review import CreditFinding
        audit.findings.append(CreditFinding('pdf_error', 'Unreadable extra document', True))
    with pytest.raises(ValueError, match='cannot be corrected'):
        build_credit_correction_plan(audit, policy)


def test_dry_run_and_live_updates_verify_finances_and_repeat_is_noop(records):
    policy, audit, books = records
    plan = build_credit_correction_plan(audit, policy)
    assert execute_credit_correction(books, plan).status == 'preview'
    assert not books.vendor_credits.updates
    checkpoints = []
    result = execute_credit_correction(books, plan, dry_run=False,
                                      checkpoint=lambda r: checkpoints.append(deepcopy(r)))
    assert result.status == 'verified' and result.completed == ['vc', 'journal', 'payment']
    assert any(x.pending == 'vc' for x in checkpoints)
    assert result.after['payment']['invoices'] == audit.payment['invoices']
    new_audit = CreditAudit(result.after['vc'], audit.memos, result.after['journal'], result.after['payment'], [], 'reference', 'reference')
    plan2 = build_credit_correction_plan(new_audit, policy)
    execute_credit_correction(books, plan2, dry_run=False, checkpoint=lambda r: None)
    assert len(books.vendor_credits.updates) == len(books.journals.updates) == len(books.customer_payments.updates) == 1


def test_stale_plan_and_tampered_payload_fail_before_writes(records):
    policy, audit, books = records
    plan = build_credit_correction_plan(audit, policy)
    books.customer_payments.records['p']['amount'] = 99
    with pytest.raises(ValueError, match='changed since planning'):
        execute_credit_correction(books, plan, dry_run=False, checkpoint=lambda r: None)
    assert not books.vendor_credits.updates
    plan.payloads['payment']['amount'] = 99
    with pytest.raises(ValueError, match='changed after planning'):
        execute_credit_correction(books, plan)


def test_partial_failure_and_readback_failure_keep_pending_checkpoint(records):
    policy, audit, books = records
    plan = build_credit_correction_plan(audit, policy)
    books.customer_payments.mutate = lambda row: row.update(amount=99)
    checkpoints = []
    with pytest.raises(CreditCorrectionError, match='verification failed') as error:
        execute_credit_correction(books, plan, dry_run=False,
                                 checkpoint=lambda r: checkpoints.append(deepcopy(r)))
    assert error.value.result.completed == ['vc', 'journal']
    assert error.value.result.pending == 'payment'
    assert checkpoints[-1].status == 'failed'


def test_unacknowledged_journal_update_stops_before_payment(records):
    policy, audit, books = records
    books.journals.update = Mock(side_effect=TimeoutError('uncertain journal write'))
    with pytest.raises(CreditCorrectionError) as error:
        execute_credit_correction(books, build_credit_correction_plan(audit, policy),
                                  dry_run=False, checkpoint=lambda r: None)
    assert error.value.result.pending == 'journal' and error.value.result.completed == ['vc']
    assert not books.customer_payments.updates


def test_live_execution_requires_checkpoint_and_customer_invoice_preflight(records):
    policy, audit, books = records
    plan = build_credit_correction_plan(audit, policy)
    with pytest.raises(ValueError, match='checkpoint'):
        execute_credit_correction(books, plan, dry_run=False)
    books.invoices.records['i']['customer_id'] = 'other'
    with pytest.raises(ValueError, match='invoice identity'):
        execute_credit_correction(books, plan, dry_run=False, checkpoint=lambda r: None)
    assert not books.vendor_credits.updates


def test_orchestration_scope_reads_real_document_list_and_links(records, tmp_path, monkeypatch):
    policy, audit, books = records
    # Even when the list flag is false, detail documents are authoritative.
    books.vendor_credits.records['vc']['has_attachment'] = False
    wrong = deepcopy(audit.credit)
    wrong.update(vendor_credit_id='other', vendor_id='999')
    books.vendor_credits.records['other'] = wrong
    monkeypatch.setattr('workflows.polycab_credit_review.workflow.download_books_document', lambda b, resource, vc, doc, path: path)
    memos = iter(audit.memos)
    result = review_polycab_vendor_credits(books, policy=policy, from_date=date(2025, 4, 1),
        to_date=date(2026, 3, 31), credit_numbers=['1001'], output_dir=tmp_path,
        pdf_reader=lambda path: next(memos))
    assert len(result) == 1 and result[0].correction_allowed
    assert result[0].payment['payment_id'] == 'p'
    with pytest.raises(ValueError, match='not found in scope'):
        review_polycab_vendor_credits(books, policy=policy, from_date=date(2025, 4, 1),
                                      to_date=date(2026, 3, 31), credit_numbers=['missing'], output_dir=tmp_path)


def test_missing_attachment_and_pdf_failure_are_reported(records, tmp_path, monkeypatch):
    policy, _, books = records
    books.vendor_credits.records['vc']['documents'] = []
    result = review_polycab_vendor_credits(books, policy=policy, from_date=date(2025, 4, 1), to_date=date(2026, 3, 31), output_dir=tmp_path)
    assert any(f.code == 'missing_attachment' for f in result[0].findings)
    assert not result[0].correction_allowed
    books.vendor_credits.records['vc']['documents'] = [{'document_id': 'd', 'file_name': 'a.pdf'}]
    monkeypatch.setattr('workflows.polycab_credit_review.workflow.download_books_document', Mock(side_effect=ValueError('not PDF')))
    result = review_polycab_vendor_credits(books, policy=policy, from_date=date(2025, 4, 1), to_date=date(2026, 3, 31), output_dir=tmp_path)
    assert any(f.code == 'pdf_error' and f.blocking for f in result[0].findings)


def test_shared_native_links_block_separate_credits(records):
    from workflows.polycab_credit_review.rules import flag_shared_links
    policy, audit, _ = records
    other = deepcopy(audit)
    other.credit['vendor_credit_id'] = 'other'
    flagged = flag_shared_links([audit, other])
    assert all(not x.correction_allowed for x in flagged)
    with pytest.raises(ValueError, match='shared'):
        build_credit_correction_plan(flagged[0], policy)


def test_public_plan_cannot_correct_another_vendor(records):
    policy, audit, _ = records
    audit.credit['vendor_id'] = '999'
    with pytest.raises(ValueError, match='configured vendor'):
        build_credit_correction_plan(audit, policy)


def cli_args(tmp_path):
    return ['--vendor-id', '1', '--customer-id', '2', '--rma-item-id', '3',
            '--rma-account-id', '4', '--clearing-account-id', '5',
            '--output-dir', str(tmp_path)]


def test_cli_dry_run_writes_review_and_preview_without_mutation(records, tmp_path, monkeypatch):
    import json
    from apps import review_polycab_vendor_credits as app
    _, audit, books = records
    monkeypatch.setattr(app, 'get_books_client', lambda: books)
    monkeypatch.setattr(app, 'review_polycab_vendor_credits', lambda *a, **kw: [audit])
    assert app.main(cli_args(tmp_path) + ['--fy', '25-26', '--credit', '1001']) == 0
    report = json.loads(next(tmp_path.glob('review_*.json')).read_text())
    assert report['from_date'] == '2025-04-01' and report['results'][0]['dry_run'] is True
    assert not books.vendor_credits.updates


def test_cli_apply_requires_selection_and_stops_all_for_blocked_credit(records, tmp_path, monkeypatch):
    from apps import review_polycab_vendor_credits as app
    _, audit, books = records
    client = Mock(return_value=books)
    monkeypatch.setattr(app, 'get_books_client', client)
    with pytest.raises(SystemExit) as exc:
        app.main(cli_args(tmp_path) + ['--apply'])
    assert exc.value.code == 2 and not client.called
    blocked = deepcopy(audit)
    blocked.memos = ()
    monkeypatch.setattr(app, 'review_polycab_vendor_credits', lambda *a, **kw: [audit, blocked])
    assert app.main(cli_args(tmp_path) + ['--credit', '1001', '--credit', '1002', '--apply']) == 2
    assert not books.vendor_credits.updates


def test_cli_apply_persists_verified_checkpoint(records, tmp_path, monkeypatch):
    import json
    from apps import review_polycab_vendor_credits as app
    _, audit, books = records
    monkeypatch.setattr(app, 'get_books_client', lambda: books)
    monkeypatch.setattr(app, 'review_polycab_vendor_credits', lambda *a, **kw: [audit])
    assert app.main(cli_args(tmp_path) + ['--credit', '1001', '--apply']) == 0
    checkpoint = json.loads(next(tmp_path.glob('checkpoint_*.json')).read_text())
    assert checkpoint['result']['status'] == 'verified'
    assert checkpoint['result']['completed'] == ['vc', 'journal', 'payment']


def test_workflow_root_exports_supported_review_apis():
    from workflows import CreditCorrectionError as RootError, RmaCreditPolicy as RootPolicy
    assert RootError is CreditCorrectionError and RootPolicy is RmaCreditPolicy
