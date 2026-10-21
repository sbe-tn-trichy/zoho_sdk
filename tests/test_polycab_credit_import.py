from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from workflows.polycab_credit_memos import CreditImportPolicy, import_credit_pdf
from workflows.polycab_credit_review.models import CreditMemoEvidence


@pytest.fixture
def setup_import(tmp_path):
    books = MagicMock()
    policy = CreditImportPolicy('1', '2', '3', '4', '5', '6')
    memo = CreditMemoEvidence('100', 'TN/CN100', date(2026, 10, 8), Decimal('50'), '200', 'SBE2627INV-1', True)
    invoice = dict(invoice_id='7', invoice_number=memo.invoice_number, location_id='2',
                   customer_id='8', status='sent', balance=100)
    books.contacts.get.return_value = {'contact': dict(contact_id='1', contact_type='vendor', status='active')}
    accounts = {'4': ('Polycab Kitty', 'other_current_liability'), '5': ('RMA Expense', 'other_expense'), '6': ('Vendor To Customer', 'bank')}
    books.chart_of_accounts.get.side_effect = lambda identifier: {'chart_of_account': {
        'account_id': identifier, 'account_name': accounts[identifier][0],
        'account_type': accounts[identifier][1], 'is_active': True}}
    books.vendor_credits.list_all.return_value = []
    books.invoices.list_all.return_value = [invoice]
    books.invoices.get.side_effect = lambda identifier: {'invoice': deepcopy(invoice)}
    for resource, key, id_key, number_key in (
        (books.vendor_credits, 'vendor_credit', 'vendor_credit_id', 'vendor_credit_number'),
        (books.journals, 'journal', 'journal_id', 'entry_number'),
        (books.customer_payments, 'payment', 'payment_id', 'payment_number'),
    ):
        store = {}
        def create(payload, store=store, key=key, id_key=id_key, number_key=number_key):
            store.update(deepcopy(payload), **{id_key: '10', number_key: payload.get(number_key, 'N10')})
            if key == 'payment':
                invoice['balance'] -= payload['amount']
            if key == 'vendor_credit':
                store['total'] = 50
                store['line_items'][0]['line_item_id'] = '11'
            return {key: deepcopy(store)}
        def update(identifier, payload, store=store):
            store.update(deepcopy(payload))
            return {'code': 0}
        resource.create.side_effect = create
        resource.update.side_effect = update
        resource.get.side_effect = lambda identifier, store=store, key=key: {key: deepcopy(store)}
        if key == 'journal':
            resource.publish.side_effect = lambda identifier, store=store: store.update(status='published')
        if key == 'vendor_credit':
            resource.add_attachment.side_effect = lambda *args, store=store: store.update(documents=[{'document_id': '12'}])
    return books, policy, memo, tmp_path / 'checkpoint.json'


def run_import(setup_import, **kwargs):
    books, policy, memo, checkpoint = setup_import
    with patch('workflows.polycab_credit_memos.importer.read_credit_memo_pdf', return_value=memo):
        return import_credit_pdf(books, checkpoint.parent / 'source.pdf', policy=policy,
                                 checkpoint_path=checkpoint, **kwargs)


def test_preview_has_no_mutations(setup_import):
    result = run_import(setup_import)
    assert result['status'] == 'preview'
    setup_import[0].vendor_credits.create.assert_not_called()
    assert not setup_import[3].exists()


def test_rso_creates_and_cross_references_all_three(setup_import):
    result = run_import(setup_import, apply=True)
    assert result['status'] == 'verified'
    for name in ('credit', 'journal', 'payment'):
        record = result['records'][name]
        assert not record.get('notes')
        notes = record['description'] if name == 'payment' else record['line_items'][0]['description']
        for reference in ('SUPPLIER_CN#: 100', 'RSO#: 200', 'INV#: SBE2627INV-1', 'VC#:', 'JNL#:', 'CP#:'):
            assert reference in notes
    journal = result['records']['journal']
    assert [(x['account_id'], x['debit_or_credit']) for x in journal['line_items']] == [('5', 'debit'), ('6', 'credit')]
    assert result['records']['payment']['invoices'] == [{'invoice_id': '7', 'amount_applied': 50}]
    assert result['records']['credit']['line_items'][0]['item_id'] == '1094368000028456138'


def test_scheme_only_uses_kitty(setup_import):
    from dataclasses import replace
    books, policy, memo, checkpoint = setup_import
    result = run_import((books, policy, replace(memo, is_return=False, rso_number='', invoice_number=''), checkpoint), apply=True)
    assert result['records']['credit']['line_items'][0]['account_id'] == '4'
    books.journals.create.assert_not_called()
    books.customer_payments.create.assert_not_called()


@pytest.mark.parametrize('failure', ['missing_invoice', 'insufficient_balance', 'duplicate', 'missing_rso', 'checkpoint'])
def test_preflight_blocks_all_writes(setup_import, failure):
    from dataclasses import replace
    books, policy, memo, checkpoint = setup_import
    if failure == 'missing_invoice':
        books.invoices.list_all.return_value = []
    elif failure == 'insufficient_balance':
        books.invoices.get.side_effect = lambda identifier: {'invoice': {**books.invoices.list_all.return_value[0], 'balance': 10}}
    elif failure == 'duplicate':
        books.vendor_credits.list_all.return_value = [{'vendor_id': '1', 'vendor_credit_number': '100'}]
    elif failure == 'missing_rso':
        memo = replace(memo, rso_number='')
    else:
        checkpoint.write_text('{}')
    with pytest.raises(ValueError):
        run_import((books, policy, memo, checkpoint), apply=True)
    books.vendor_credits.create.assert_not_called()


def test_partial_failure_checkpoint_prevents_retry(setup_import):
    import json
    books, _, _, checkpoint = setup_import
    books.journals.create.side_effect = RuntimeError('connection lost')
    with pytest.raises(RuntimeError):
        run_import(setup_import, apply=True)
    state = json.loads(checkpoint.read_text())
    assert state['pending'] == 'create_journal'
    assert state['records']['credit']['vendor_credit_id'] == '10'
    books.customer_payments.create.assert_not_called()
    with pytest.raises(ValueError, match='Checkpoint already exists'):
        run_import(setup_import, apply=True)


def test_wrong_saved_payment_allocation_stops_completion(setup_import):
    books = setup_import[0]
    original = books.customer_payments.get.side_effect
    def changed(identifier):
        result = original(identifier)
        result['payment']['invoices'][0]['amount_applied'] = 1
        return result
    books.customer_payments.get.side_effect = changed
    with pytest.raises(ValueError, match='read-back mismatch'):
        run_import(setup_import, apply=True)


def test_policy_rejects_placeholder():
    with pytest.raises(ValueError, match='numeric'):
        CreditImportPolicy('<vendor>', '2', '3', '4', '5', '6')
