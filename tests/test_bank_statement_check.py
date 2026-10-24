from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from workflows.bank_statement_check import (
    StatementLine, compare_statement_lines, comparison_dict, fetch_statement_snapshot,
    parse_analytics_lines, read_hdfc_csv,
)

DAY = date(2026, 4, 1)
HEADER = 'Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n'


def line(identifier='1', reference='00123', description='UPI Customer', direction='deposit', amount='100', day=DAY):
    return StatementLine(identifier, day, direction, Decimal(amount), reference, description)


def analytics_row(**changes):
    return {'Statement Line ID': 'b1', 'Account ID': '123', 'Date': '2026-04-01',
            'Debit or Credit': 'debit', 'Amount': 'INR 100.00',
            'Reference Number': '123', 'Description': 'UPI Customer', **changes}


def test_hdfc_reader_preserves_reference_and_reads_quoted_narration(tmp_path):
    path = tmp_path / 'bank.csv'
    path.write_text('\ufeff' + HEADER + '01/04/26,"name, customer",000123,01/04/26,,100.00,200.00\n')
    rows = read_hdfc_csv(path)
    assert rows == [line('2', '000123', 'name, customer')]


@pytest.mark.parametrize('row', [
    'bad,name,1,01/04/26,,100,200',
    '01/04/26,name,1,bad,,100,200',
    '01/04/26,name,1,01/04/26,100,100,200',
    '01/04/26,name,1,01/04/26,,,200',
    '01/04/26,name,1,01/04/26,,NaN,200',
    '01/04/26,name,1,01/04/26,,-100,200',
    '01/04/26,name,1,01/04/26,,1.001,200',
    '01/04/26,name,1,01/04/26,,100',
])
def test_bad_csv_rows_fail_with_context(tmp_path, row):
    path = tmp_path / 'bank.csv'
    path.write_text(HEADER + row + '\n')
    with pytest.raises(ValueError, match='CSV line 2'):
        read_hdfc_csv(path)


def test_empty_csv_and_bad_headers_fail(tmp_path):
    path = tmp_path / 'bank.csv'
    for text in (HEADER, 'Date,Amount\n'):
        path.write_text(text)
        with pytest.raises(ValueError):
            read_hdfc_csv(path)


def test_analytics_direction_currency_and_scope():
    rows = parse_analytics_lines([analytics_row()], account_id='123', start=DAY, end=DAY)
    assert rows == [line('b1', '123')]
    rows = parse_analytics_lines([analytics_row(**{'Debit or Credit': 'credit'})], account_id='123', start=DAY, end=DAY)
    assert rows[0].direction == 'withdrawal'


@pytest.mark.parametrize('changes', [
    {'Account ID': 'other'}, {'Date': '2026-04-02'}, {'Date': 'invalid'},
    {'Debit or Credit': 'unknown'}, {'Amount': 'Infinity'}, {'Amount': '0'},
    {'Statement Line ID': ''}, {'Amount': 'USD 100'},
])
def test_invalid_analytics_records_fail(changes):
    with pytest.raises(ValueError):
        parse_analytics_lines([analytics_row(**changes)], account_id='123', start=DAY, end=DAY)


def test_duplicate_analytics_ids_fail():
    with pytest.raises(ValueError, match='duplicate'):
        parse_analytics_lines([analytics_row(), analytics_row()], account_id='123', start=DAY, end=DAY)


def test_match_requires_identity_and_preserves_direction():
    report = compare_statement_lines([line()], [line('b', '123', 'different')], account_id='123')
    assert report.results[0].status == 'matched'
    assert comparison_dict(report)['results'][0]['line']['amount'] == '100'
    for other, status in [(line('b', '999', 'other'), 'review'),
                          (line('b', direction='withdrawal'), 'missing')]:
        assert compare_statement_lines([line()], [other], account_id='123').results[0].status == status


def test_narration_match_and_zero_reference_not_identity():
    assert compare_statement_lines([line(reference='000')], [line('b', '999', ' upi   CUSTOMER ')], account_id='123').results[0].status == 'matched'
    assert compare_statement_lines([line(reference='000', description='')], [line('b', '0', '')], account_id='123').results[0].status == 'review'


def test_duplicate_multiplicity_and_unmatched_books():
    report = compare_statement_lines([line('1'), line('2')], [line('b')], account_id='123')
    assert sorted(r.status for r in report.results) == ['duplicate_shortfall', 'matched']
    report = compare_statement_lines([line()], [line('b1'), line('b2')], account_id='123')
    assert len(report.unmatched_books_ids) == 1


def test_augmenting_match_does_not_lose_valid_pairs():
    # First CSV can use either Books row; second can only use the first.
    report = compare_statement_lines(
        [line('1', '1', 'A'), line('2', '2', 'B')],
        [line('b1', '1', 'B'), line('b2', '9', 'A')], account_id='123')
    assert [r.status for r in report.results] == ['matched', 'matched']
    assert {r.books_line_id for r in report.results} == {'b1', 'b2'}


def test_fetch_uses_cached_design_and_scoped_query():
    from contextlib import contextmanager
    required = ['Statement Line ID', 'Account ID', 'Date', 'Debit or Credit', 'Amount', 'Description', 'Reference Number']
    store = SimpleNamespace(get_columns=lambda _: [{'name': name} for name in required])
    @contextmanager
    def cached():
        yield store
    catalog = SimpleNamespace(workspace_id='workspace', cached_store=cached,
        analyze=Mock(return_value={'views': [{'name': 'Bank Statements (Zoho Books)'}],
                                   'last_successful_sync_at': 'cached-time'}))
    analytics = SimpleNamespace(queries=SimpleNamespace(execute=Mock(return_value=[analytics_row()])))
    result = fetch_statement_snapshot(analytics, catalog=catalog, account_id='123', start=DAY, end=DAY)
    assert result['rows'] == [analytics_row()]
    assert result['last_successful_metadata_sync_at'] == 'cached-time'
    sql = analytics.queries.execute.call_args.args[1]
    assert '"Account ID" = \'123\'' in sql
    assert '"Date" < \'2026-04-02\'' in sql
    with pytest.raises(ValueError):
        fetch_statement_snapshot(analytics, catalog=catalog, account_id="1' OR 1=1", start=DAY, end=DAY)


def test_cli_replay_and_snapshot_scope(tmp_path, monkeypatch):
    from apps.check_hdfc_statement import main
    path, saved, output = tmp_path / 'bank.csv', tmp_path / 'saved.json', tmp_path / 'output'
    path.write_text(HEADER + '01/04/26,UPI Customer,00123,01/04/26,,100,200\n')
    snapshot = {'schema_version': 1, 'workspace_id': '264324000000002043',
        'view_id': '264324000005829009', 'account_id': '123', 'start': str(DAY), 'end': str(DAY),
        'captured_at': 'test', 'last_successful_metadata_sync_at': 'cached-time', 'rows': [analytics_row()]}
    saved.write_text(json.dumps(snapshot))
    monkeypatch.setattr('apps.check_hdfc_statement.get_analytics_client', Mock(side_effect=AssertionError('network')))
    args = [str(path), '--account-id', '123', '--saved', str(saved), '--output', str(output)]
    assert main(args) == 0
    assert 'Matched: 1' in (output / 'report.md').read_text()
    assert json.loads((output / 'comparison.json').read_text())['csv_count'] == 1
    snapshot['account_id'] = 'other'
    saved.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match='snapshot'):
        main(args)
    with pytest.raises(SystemExit):
        main([str(path), '--output', str(tmp_path)])


def test_masked_account_narration_and_full_transaction_reference():
    csv = line(reference='0000123456789012', description='UPI-814520110000080-NAME@UPI-123456789012-UPI')
    books = line('b', 'xxxxxxxxxxxx9012', 'UPI-xxxxxxxxxxx0080-NAME@UPI-123456789012-UPI')
    assert compare_statement_lines([csv], [books], account_id='123').results[0].status == 'matched'
    changed = line('b', 'xxxxxxxxxxxx9012', 'UPI-xxxxxxxxxxx0080-OTHER@UPI-999999999999-UPI')
    assert compare_statement_lines([csv], [changed], account_id='123').results[0].status == 'review'


def test_unique_masked_cheque_is_probable_and_suffix_collision_stays_review():
    csv = line(reference='0000000000174775', description='CHQ DEP - CTS CLG1 - TOWN: CUSTOMER :BANK')
    books = line('b', 'xxxxxxxxxxxx4775', 'CHQ DEP - CTS CLG1 - TOWN')
    result = compare_statement_lines([csv], [books], account_id='123')
    assert result.results[0].status == 'probable'
    assert not result.unmatched_books_ids
    other = line('2', '0000000000274775', csv.description)
    assert all(row.status == 'review' for row in compare_statement_lines([csv, other], [books], account_id='123').results)


def test_missing_date_and_amount_are_not_matched_by_reference():
    assert compare_statement_lines([line()], [line('b', amount='101')], account_id='123').results[0].status == 'missing'
    with pytest.raises(ValueError, match='period'):
        compare_statement_lines([line()], [line('b', day=date(2026, 4, 2))], account_id='123')
