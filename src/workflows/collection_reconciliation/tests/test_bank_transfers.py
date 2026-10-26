"""Internal transfer identity, live guards and interrupted-post recovery."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from workflows.collection_reconciliation import OnlinePaymentReviewConfig, OnlinePaymentReviewService
from workflows.collection_reconciliation.bank_transfers import transfer_proposals
from workflows.core.exceptions import ReconciliationError
from workflows.core.config import Config


def line(account, transaction, direction, **values):
    return dict(_review_bank_account_id=account, _review_bank_name=account.upper(),
                transaction_id=transaction, debit_or_credit=direction,
                date='2026-10-26', amount='1000.00', reference_number='UTR123',
                description='Internal transfer', **values)


def test_pair_requires_exact_identity_and_opposite_directions():
    source = line('a', 'out', 'credit')
    destination = line('b', 'in', 'debit')
    pairs = transfer_proposals([source, destination])
    assert len(pairs) == 1
    assert pairs[0]['match_status'] == 'reviewable'
    assert pairs[0]['source']['bank_account_id'] == 'a'
    assert pairs[0]['destination']['bank_account_id'] == 'b'
    for field, value in [('reference_number', ''), ('reference_number', 'UTR124'),
                         ('date', '2026-10-25'), ('date', 'invalid'), ('amount', '1000.01'),
                         ('amount', 'NaN'), ('debit_or_credit', 'credit'),
                         ('_review_bank_account_id', 'a')]:
        assert transfer_proposals([source, {**destination, field: value}]) == []
    assert transfer_proposals([source, {**destination, 'amount': '-1000', 'reference_number': ' utr123 '}])
    assert transfer_proposals([{**source, 'amount': 0}, {**destination, 'amount': 0}]) == []


def test_ambiguous_pairs_never_claim_unique_match():
    source = line('a', 'out', 'credit')
    destination = line('b', 'in', 'debit')
    for rows in ([source, destination, {**destination, 'transaction_id': 'in-2'}],
                 [source, destination, {**source, 'transaction_id': 'out-2'}]):
        pairs = transfer_proposals(rows)
        assert len(pairs) == 2
        assert all(pair['match_status'] == 'ambiguous' for pair in pairs)


def test_icici_neft_description_matches_hdfc_reference(monkeypatch):
    monkeypatch.setattr(Config, 'BANK_ACCOUNT_ICICI', 'icici')
    source = {**line('hdfc', 'out', 'credit'),
              'reference_number': 'HDFCH01313813505',
              'description': 'NEFT DR-ICIC0006134-SRI BHARATH ELECTRICALS-NETBANK, MUM-HDFCH01313813505-INVESTMENT'}
    destination = {**line('icici', 'in', 'debit'), 'reference_number': 'S48186536',
                   'description': 'NEFT-HDFCH01313813505-SRI BHARATH ELECTRICALS A UNIT OF B-0001INVESTMENT-xxxxxxxxxx7297-HDFC0000001'}
    pairs = transfer_proposals([source, destination])
    assert len(pairs) == 1
    assert pairs[0]['match_status'] == 'reviewable'
    assert pairs[0]['source']['reference'] == pairs[0]['destination']['reference'] == 'HDFCH01313813505'
    assert destination['reference_number'] == 'S48186536'
    assert not transfer_proposals([source, {**destination, 'description': 'NEFT-HDFCH01313813506-OTHER'}])


def test_explicit_expense_and_cash_rules_keep_priority():
    source, destination = line('a', 'out', 'credit'), line('b', 'in', 'debit')
    for description in ('Salary', 'TNPDCL', 'Employee/TA', 'POLY2300277498'):
        assert transfer_proposals([{**source, 'description': description}, destination]) == []
    assert transfer_proposals([source, {**destination, 'description': 'CASH DEPOSIT'}]) == []


@pytest.fixture
def transfer_review(tmp_path):
    books, creator = MagicMock(), MagicMock()
    creator.get_all_records.return_value = []
    state = {'rows': [line('a', 'out', 'credit'), line('b', 'in', 'debit')], 'transfer': None}
    def list_rows(params):
        if params.get('transaction_type') == 'transfer_fund':
            return [deepcopy(state['transfer'])] if state['transfer'] else []
        return [deepcopy(row) for row in state['rows'] if row['_review_bank_account_id'] == params['account_id']]
    books.bank_transactions.list_all.side_effect = list_rows
    books.bank_accounts.get.side_effect = lambda account: {'code': 0, 'bankaccount': {
        'account_id': account, 'account_type': 'bank', 'is_active': True, 'currency_id': 'inr'}}
    def create(payload):
        state['transfer'] = {**payload, 'transaction_id': 'native-transfer', 'imported_transactions': []}
        return {'code': 0, 'banktransaction': deepcopy(state['transfer'])}
    books.bank_transactions.create.side_effect = create
    books.bank_transactions.get.side_effect = lambda transfer: {'code': 0, 'banktransaction': deepcopy(state['transfer'])}
    books.bank_transactions.get_matches.side_effect = lambda transaction: {'code': 0, 'matching_transactions': (
        [{'transaction_id': 'native-transfer', 'transaction_type': 'transfer_fund'}] if state['transfer'] else [])}
    def match(transaction, payload):
        row = next(row for row in state['rows'] if row['transaction_id'] == transaction)
        state['transfer']['imported_transactions'].append({'account_id': row['_review_bank_account_id'], 'imported_transaction_id': transaction})
        state['rows'].remove(row)
        return {'code': 0}
    books.bank_transactions.match.side_effect = match
    service = OnlinePaymentReviewService(creator, books, OnlinePaymentReviewConfig(
        creator_app_link_name='app', bank_accounts=(('A', 'a'), ('B', 'b')),
        state_path=tmp_path/'review.json'))
    service.refresh()
    return service, books, state


def test_one_transfer_matches_both_lines_and_repeat_is_idempotent(transfer_review):
    service, books, state = transfer_review
    pair = service.load()['bank_transfers'][0]
    assert {row['kind'] for row in service.load()['bank_records']} == {'bank_transfer'}
    assert service.categorize_bank_transfer(pair['id'])['status'] == 'completed'
    payload = books.bank_transactions.create.call_args.args[0]
    assert (payload['from_account_id'], payload['to_account_id'], payload['amount']) == ('a', 'b', 1000)
    assert payload['transaction_type'] == 'transfer_fund'
    assert books.bank_transactions.match.call_count == 2
    assert not state['rows']
    assert all(row['categorization_status'] == 'categorized' for row in service.load()['bank_records'])
    service.categorize_bank_transfer(pair['id'])
    books.bank_transactions.create.assert_called_once()
    assert books.bank_transactions.match.call_count == 2


def test_stale_line_or_new_ambiguity_blocks_all_writes(transfer_review):
    service, books, state = transfer_review
    pair = service.load()['bank_transfers'][0]
    state['rows'][1]['amount'] = 999
    with pytest.raises(ReconciliationError, match='no longer a unique'):
        service.categorize_bank_transfer(pair['id'])
    books.bank_transactions.create.assert_not_called()
    state['rows'][1]['amount'] = 1000
    state['rows'].append({**state['rows'][1], 'transaction_id': 'another'})
    with pytest.raises(ReconciliationError, match='no longer a unique'):
        service.categorize_bank_transfer(pair['id'])
    books.bank_transactions.create.assert_not_called()


def test_refresh_reserves_internal_transfer_from_creator_matching(transfer_review):
    service, books, state = transfer_review
    service.creator.get_all_records.side_effect = lambda app, report, **kwargs: (
        [{'ID': 'customer', 'Customer_Id': 'books-customer'}] if report == 'All_Customers1' else [
            {'ID': 'payment', 'Payment_Date': '2026-10-26', 'Payment_Amount': 1000,
             'Reference': 'UTR123', 'Customer_Name': {'ID': 'customer'}}])
    batch = service.refresh(force_refresh=True)
    assert batch['entries'][0]['bank'] is None
    assert not batch['entries'][0]['reviewable']
    assert all(not row['creator_entry_ids'] for row in batch['bank_records'])


def test_resume_after_first_match_and_refresh_does_not_create_again(transfer_review):
    service, books, state = transfer_review
    pair_id = service.load()['bank_transfers'][0]['id']
    original = books.bank_transactions.match.side_effect
    def fail_second(transaction, payload):
        if transaction == 'in':
            raise RuntimeError('offline')
        return original(transaction, payload)
    books.bank_transactions.match.side_effect = fail_second
    with pytest.raises(RuntimeError, match='offline'):
        service.categorize_bank_transfer(pair_id)
    assert service.load()['bank_transfers'][0]['transfer_id'] == 'native-transfer'
    refreshed = service.refresh()
    assert refreshed['bank_transfers'][0]['id'] == pair_id
    assert any(row.get('recovery_checkpoint') for row in refreshed['bank_records'])
    books.bank_transactions.match.side_effect = original
    assert service.categorize_bank_transfer(pair_id)['status'] == 'completed'
    books.bank_transactions.create.assert_called_once()


def test_uncertain_creation_is_recovered_by_marker(transfer_review):
    service, books, state = transfer_review
    original = books.bank_transactions.create.side_effect
    def timeout(payload):
        original(payload)
        raise RuntimeError('timeout')
    books.bank_transactions.create.side_effect = timeout
    pair_id = service.load()['bank_transfers'][0]['id']
    with pytest.raises(RuntimeError, match='timeout'):
        service.categorize_bank_transfer(pair_id)
    assert service.load()['bank_transfers'][0]['status'] == 'create_requested'
    service.refresh()
    assert service.categorize_bank_transfer(pair_id)['status'] == 'completed'
    books.bank_transactions.create.assert_called_once()


def test_uncertain_creation_with_no_evidence_never_repeats_create(transfer_review):
    service, books, state = transfer_review
    pair_id = service.load()['bank_transfers'][0]['id']
    books.bank_transactions.create.side_effect = RuntimeError('timeout')
    with pytest.raises(RuntimeError):
        service.categorize_bank_transfer(pair_id)
    with pytest.raises(ReconciliationError, match='outcome is uncertain'):
        service.categorize_bank_transfer(pair_id)
    books.bank_transactions.create.assert_called_once()


def test_missing_readback_match_is_not_reported_successful(transfer_review):
    service, books, state = transfer_review
    pair_id = service.load()['bank_transfers'][0]['id']
    books.bank_transactions.match.side_effect = None
    books.bank_transactions.match.return_value = {'code': 0}
    with pytest.raises(ReconciliationError, match='did not verify'):
        service.categorize_bank_transfer(pair_id)
    assert service.load()['bank_transfers'][0]['status'] != 'completed'


def test_existing_transfer_is_reused(transfer_review):
    service, books, state = transfer_review
    pair = service.load()['bank_transfers'][0]
    state['transfer'] = {'transaction_id': 'native-transfer', 'transaction_type': 'transfer_fund',
                         'from_account_id': 'a', 'to_account_id': 'b', 'amount': 1000,
                         'date': '2026-10-26', 'reference_number': 'UTR123', 'imported_transactions': []}
    assert service.categorize_bank_transfer(pair['id'])['status'] == 'completed'
    books.bank_transactions.create.assert_not_called()


def test_currency_mismatch_blocks_posting(transfer_review):
    service, books, state = transfer_review
    books.bank_accounts.get.side_effect = lambda account: {'code': 0, 'bankaccount': {
        'account_id': account, 'account_type': 'bank', 'currency_id': account}}
    with pytest.raises(ReconciliationError, match='same known currency'):
        service.categorize_bank_transfer(service.load()['bank_transfers'][0]['id'])
    books.bank_transactions.create.assert_not_called()
