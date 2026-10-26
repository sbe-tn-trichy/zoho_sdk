"""Exact internal bank-transfer proposals and restartable paired matching."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from ..core.exceptions import ReconciliationError
from ..core.matching import get_bank_reference, parse_date, to_decimal, to_text
from .bank_statement import bank_line_kind
from .identifiers import identifier
from .types import BankTransferProposal


def bank_line_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return (to_text(row.get('_review_bank_account_id') or row.get('bank_account_id')),
            to_text(row.get('transaction_id') or row.get('id')))


def _line(row: Mapping[str, Any]) -> dict[str, str]:
    account, transaction = bank_line_identity(row)
    return dict(bank_account_id=account, transaction_id=transaction,
                bank_name=to_text(row.get('_review_bank_name') or row.get('bank_name')),
                date=to_text(row.get('date') or row.get('transaction_date')),
                amount=to_text(row.get('amount')),
                reference=to_text(get_bank_reference(row, account)),
                description=to_text(row.get('description') or row.get('narration')))


def transfer_proposals(rows: Sequence[Mapping[str, Any]]) -> list[BankTransferProposal]:
    """Only mutually unique cross-bank, opposite-direction matches are ready."""
    groups: dict[tuple[Any, Any, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        day = parse_date(row.get('date') or row.get('transaction_date'))
        amount = to_decimal(row.get('amount'))
        account, transaction = bank_line_identity(row)
        reference = to_text(get_bank_reference(row, account)).casefold()
        if (account and transaction and day and amount is not None and amount != 0
                and reference and bank_line_kind(row) in {'deposit', 'withdrawal'}):
            groups[day, abs(amount), reference].append(row)
    proposals = []
    for group in groups.values():
        withdrawals = [row for row in group if bank_line_kind(row) == 'withdrawal']
        deposits = [row for row in group if bank_line_kind(row) == 'deposit']
        for source in withdrawals:
            candidates = [row for row in deposits if bank_line_identity(row)[0] != bank_line_identity(source)[0]]
            for destination in candidates:
                reverse = [row for row in withdrawals if bank_line_identity(row)[0] != bank_line_identity(destination)[0]]
                unique = len(candidates) == len(reverse) == 1
                key = repr((bank_line_identity(source), bank_line_identity(destination)))
                proposals.append(BankTransferProposal(
                    id=hashlib.sha256(key.encode()).hexdigest()[:24],
                    source=_line(source), destination=_line(destination),
                    match_status='reviewable' if unique else 'ambiguous',
                    status='pending', transfer_id='', error='',
                ))
    return proposals


def validate_live_pair(proposal: BankTransferProposal, rows: Sequence[Mapping[str, Any]]) -> None:
    """Check identity, reviewed values and mutual uniqueness against a fresh feed."""
    fresh = next((pair for pair in transfer_proposals(rows) if pair['id'] == proposal['id']), None)
    if fresh is None or fresh['match_status'] != 'reviewable':
        raise ReconciliationError('The bank transfer is no longer a unique uncategorized pair. Refresh the queue.')
    for side in ('source', 'destination'):
        old, current = proposal[side], fresh[side]
        if (bank_line_identity(old) != bank_line_identity(current)
                or parse_date(old['date']) != parse_date(current['date'])
                or to_decimal(old['amount']) != to_decimal(current['amount'])
                or old['reference'] != current['reference']
                or old['description'] != current['description']):
            raise ReconciliationError('A reviewed bank transfer line changed. Refresh the queue.')


def _require_success(response: Any, action: str) -> None:
    if not isinstance(response, Mapping) or to_text(response.get('code')) != '0':
        raise ReconciliationError(f'Books rejected {action}.')


def _transfer_detail(books: Any, proposal: BankTransferProposal, transfer_id: str) -> Mapping[str, Any]:
    response = books.bank_transactions.get(transfer_id)
    _require_success(response, 'bank transfer verification')
    transaction = response.get('banktransaction')
    if not isinstance(transaction, Mapping):
        raise ReconciliationError('Books returned no bank transfer detail.')
    source, destination = proposal['source'], proposal['destination']
    amount = to_decimal(transaction.get('amount'))
    if (to_text(transaction.get('transaction_id')) != transfer_id
            or to_text(transaction.get('transaction_type')) != 'transfer_fund'
            or to_text(transaction.get('from_account_id')) != source['bank_account_id']
            or to_text(transaction.get('to_account_id')) != destination['bank_account_id']
            or parse_date(transaction.get('date')) != parse_date(source['date'])
            or amount is None or abs(amount) != abs(to_decimal(source['amount']))
            or to_text(transaction.get('reference_number')).casefold() != source['reference'].casefold()):
        raise ReconciliationError('The saved bank transfer does not match the reviewed banks, date, amount and reference.')
    return transaction


def _validate_accounts(books: Any, proposal: BankTransferProposal) -> None:
    currencies = []
    for line in (proposal['source'], proposal['destination']):
        response = books.bank_accounts.get(line['bank_account_id'])
        _require_success(response, 'bank account validation')
        account = response.get('bankaccount')
        if (not isinstance(account, Mapping)
                or to_text(account.get('account_id')) != line['bank_account_id']
                or to_text(account.get('account_type')) != 'bank'
                or account.get('is_active') is False
                or to_text(account.get('status')).casefold() == 'inactive'):
            raise ReconciliationError('Both transfer accounts must be active Books bank accounts.')
        currencies.append(to_text(account.get('currency_id') or account.get('currency_code')))
    if not all(currencies) or currencies[0] != currencies[1]:
        raise ReconciliationError('Bank transfers require two accounts with the same known currency.')


def _import_ids(transaction: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {(to_text(row.get('account_id')), to_text(row.get('imported_transaction_id')))
            for row in transaction.get('imported_transactions', []) if isinstance(row, Mapping)}


def post_transfer(books: Any, proposal: BankTransferProposal,
                  live_rows: Sequence[Mapping[str, Any]], checkpoint: Callable[[], None]) -> None:
    """Create one ledger transfer, then match both lines, checkpointing each step.

    An uncertain create is never repeated. Its unique description marker allows
    safe recovery after a timeout or a crash before the returned ID was saved.
    """
    if proposal['status'] == 'completed':
        return
    if proposal['match_status'] != 'reviewable':
        raise ReconciliationError('Ambiguous bank transfers cannot be posted.')
    source, destination = proposal['source'], proposal['destination']
    _validate_accounts(books, proposal)
    marker = f"[bank-transfer:{proposal['id']}]"
    transfer_id = proposal.get('transfer_id', '')
    if not transfer_id:
        if proposal['status'] == 'pending':
            validate_live_pair(proposal, live_rows)
            # Reuse one existing transfer offered for both lines, if present.
            candidates = []
            for line in (source, destination):
                response = books.bank_transactions.get_matches(line['transaction_id'])
                _require_success(response, 'bank transfer candidate lookup')
                candidates.append({to_text(row.get('transaction_id')) for row in response.get('matching_transactions', [])
                                   if isinstance(row, Mapping) and row.get('transaction_type') == 'transfer_fund'})
            existing = []
            for candidate_id in sorted((candidates[0] & candidates[1]) - {''}):
                try:
                    _transfer_detail(books, proposal, candidate_id)
                except ReconciliationError as exc:
                    if not str(exc).startswith('The saved bank transfer does not match'):
                        raise
                    continue
                existing.append(candidate_id)
            if len(existing) > 1:
                raise ReconciliationError('Multiple existing Books transfers match this pair. Review them in Books.')
            if existing:
                transfer_id = existing[0]
            else:
                proposal['status'] = 'create_requested'
                checkpoint()
                response = books.bank_transactions.create({
                    'from_account_id': source['bank_account_id'],
                    'to_account_id': destination['bank_account_id'],
                    'transaction_type': 'transfer_fund',
                    'date': parse_date(source['date']).isoformat(),
                    'amount': float(abs(to_decimal(source['amount']))),
                    'reference_number': source['reference'],
                    'description': f"Internal bank transfer {source['bank_name']} to {destination['bank_name']} {marker}",
                })
                if isinstance(response, Mapping) and to_text(response.get('code')) not in {'', '0'}:
                    # A definite API rejection is safe to retry after correction.
                    proposal['status'] = 'pending'
                    checkpoint()
                _require_success(response, 'bank transfer creation')
                transfer_id = identifier(response, ('transaction_id',)) or ''
        if not transfer_id:
            # A request may have reached Books before its response was lost.
            rows = books.bank_transactions.list_all(params={'account_id': source['bank_account_id'], 'transaction_type': 'transfer_fund'})
            ids = {to_text(row.get('transaction_id')) for row in rows if marker in to_text(row.get('description'))}
            if len(ids) != 1 or '' in ids:
                raise ReconciliationError('The previous transfer creation outcome is uncertain. Review Books before retrying; no second transfer was created.')
            transfer_id = ids.pop()
        proposal.update(transfer_id=transfer_id, status='transfer_created')
        checkpoint()
    transaction = _transfer_detail(books, proposal, transfer_id)
    known_imports = {bank_line_identity(line) for line in (source, destination)}
    if _import_ids(transaction) - known_imports:
        raise ReconciliationError('The Books transfer is linked to a different bank statement line.')
    for side, line in (('source', source), ('destination', destination)):
        if bank_line_identity(line) in _import_ids(transaction):
            continue
        current = next((row for row in live_rows if bank_line_identity(row) == bank_line_identity(line)), None)
        if current is None or _line(current) != line:
            raise ReconciliationError('A bank transfer line is no longer unchanged and uncategorized. Refresh before retrying.')
        response = books.bank_transactions.get_matches(line['transaction_id'])
        _require_success(response, 'bank transfer candidate lookup')
        if not any(to_text(row.get('transaction_id')) == transfer_id and row.get('transaction_type') == 'transfer_fund'
                   for row in response.get('matching_transactions', []) if isinstance(row, Mapping)):
            raise ReconciliationError('The saved Books transfer is not offered as a match for this bank line. Retry after reviewing Books.')
        proposal['status'] = f'{side}_match_requested'
        checkpoint()
        response = books.bank_transactions.match(line['transaction_id'], [{'transaction_id': transfer_id, 'transaction_type': 'transfer_fund'}])
        _require_success(response, 'bank transfer matching')
        transaction = _transfer_detail(books, proposal, transfer_id)
        if bank_line_identity(line) not in _import_ids(transaction):
            raise ReconciliationError('Books did not verify the saved bank transfer match. Retry to recheck its state.')
        proposal['status'] = f'{side}_matched'
        checkpoint()
    if not known_imports <= _import_ids(transaction):
        raise ReconciliationError('Both bank transfer lines have not been verified in Books.')
    proposal.update(status='completed', error='', completed_at=datetime.now(timezone.utc).isoformat())
    checkpoint()
