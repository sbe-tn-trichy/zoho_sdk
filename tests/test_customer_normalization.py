import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.customer_normalization import (
    SOURCE_NAMES, build_normalized_customers, download_customer_normalization_sources,
)


def sources(tmp_path: Path, *, customers=None, addresses=None, persons=None) -> Path:
    data = {
        'customers': customers if customers is not None else [{
            'Customer ID': '10000000000000000001', 'Customer Name': ' Shop ',
            'Display Name': 'Other name', 'Credit Limit': '0012.30',
            'Payment Terms Label': 'Due On Receipt', 'Beat': ' North  Route ',
            'Status': 'Active', 'Status_1': 'Recovery', 'Default Address ID': '01',
            'PAN Number': 'abcde1234f', 'GSTIN': '33ABCDE1234F1Z5',
            'Phone': '0123-456-789', 'Email': 'AbC@EXAMPLE.COM',
            'Notes': ' preserve\n spacing ', 'New Future Field': ' kept ',
        }],
        'addresses': addresses if addresses is not None else [{
            'Address ID': '01', 'Customer ID': '10000000000000000001',
            'Billing City': ' City ', 'Shipping City': ' Another City ',
            'Billing Street': ' 1,  Road ', 'Shipping Code': '001234',
        }],
        'contact_persons': persons if persons is not None else [
            {'Contact Person ID': '01', 'Customer ID': '10000000000000000001',
             'Email': 'Secondary@EXAMPLE.COM', 'Phone': '123456/234567'},
            {'Contact Person ID': '02', 'Customer ID': '10000000000000000001',
             'Email': '', 'Phone': '+91 (987) 654-3210'},
        ],
    }
    source = tmp_path / 'source'
    source.mkdir()
    manifest = {'organization_id': 'org', 'last_metadata_sync': '2026-10-27T17:03:36Z',
                'captured_at': '2026-10-27T17:22:04Z', 'workspace_id': 'workspace', 'views': {}}
    for key, records in data.items():
        (source / f'{key}.json').write_text(json.dumps(records), encoding='utf-8')
        manifest['views'][key] = {'name': SOURCE_NAMES[key], 'view_id': key, 'rows': len(records),
                                  'columns': list(records[0]) if records else (
                                      ['Address ID', 'Customer ID'] if key == 'addresses'
                                      else ['Contact Person ID', 'Customer ID'])}
    (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return source


def test_four_tables_preserve_sources_and_normalize(tmp_path):
    source = sources(tmp_path)
    result = build_normalized_customers(source, tmp_path / 'customers.db', organization_id='org')
    db = sqlite3.connect(result.database)
    db.row_factory = sqlite3.Row
    assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
        'Customers', 'Customer Addresses', 'Customer Financials', 'Customer Beat'}
    customer = dict(db.execute('SELECT * FROM Customers').fetchone())
    assert customer['Customer Name'] == 'Shop'
    assert customer['Display Name'] == 'Other name'
    assert customer['Status'] == 'Active' and customer['Status_1'] == 'Recovery'
    assert customer['Phone'] == '0123456789'
    assert customer['Email'] == 'AbC@example.com'
    assert customer['New Future Field'] == 'kept'
    assert customer['Notes'] == ' preserve\n spacing '
    assert 'Credit Limit' not in customer and 'Beat' not in customer
    finance = db.execute('SELECT * FROM "Customer Financials"').fetchone()
    assert finance['Credit Limit'] == '0012.30'
    assert finance['Payment Terms Label'] == 'Due on Receipt'
    assert finance['PAN Number'] == 'ABCDE1234F'
    beat = db.execute('SELECT * FROM "Customer Beat"').fetchone()
    assert beat['Beat'] == 'North Route'
    address = db.execute('SELECT * FROM "Customer Addresses"').fetchone()
    assert address['Address ID'] == '01' and address['Shipping Code'] == '001234'
    assert address['Billing Street'] == '1,  Road'
    assert address['Billing City'] == 'CITY' and address['Shipping City'] == 'ANOTHER CITY'
    assert json.loads(customer['_source_json']) == json.loads((source / 'customers.json').read_text())[0]
    persons = json.loads(customer['Contact Persons'])
    assert len(persons) == 2 and persons[0]['Phone'] == '123456/234567'
    assert persons[1]['Phone'] == '+919876543210'
    assert json.loads(customer['_source_contact_persons_json']) == json.loads((source / 'contact_persons.json').read_text())
    report = json.loads(result.report.read_text(encoding='utf-8'))
    assert report['cloud_updates'] == 0 and report['contact_persons_preserved'] == 2
    assert any('Phone needs review' in i['reason'] for i in report['review_issues'])
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()


@pytest.mark.parametrize('problem', ['duplicate', 'orphan', 'wrong_org', 'missing_column', 'wrong_count', 'float_id'])
def test_invalid_source_fails_without_creating_database(tmp_path, problem):
    source = sources(tmp_path)
    manifest = json.loads((source / 'manifest.json').read_text())
    customers = json.loads((source / 'customers.json').read_text())
    if problem == 'duplicate':
        customers.append(customers[0])
        manifest['views']['customers']['rows'] = 2
    elif problem == 'orphan':
        persons = json.loads((source / 'contact_persons.json').read_text())
        persons[0]['Customer ID'] = '99'
        (source / 'contact_persons.json').write_text(json.dumps(persons))
    elif problem == 'wrong_org':
        manifest['organization_id'] = 'other'
    elif problem == 'missing_column':
        customers[0].pop('Phone')
    elif problem == 'wrong_count':
        manifest['views']['customers']['rows'] = 10
    else:
        customers[0]['Customer ID'] = 10000000000000000001.0
    (source / 'customers.json').write_text(json.dumps(customers))
    (source / 'manifest.json').write_text(json.dumps(manifest))
    destination = tmp_path / 'new.db'
    with pytest.raises(ValueError):
        build_normalized_customers(source, destination, organization_id='org')
    assert not destination.exists()


def test_existing_database_is_never_overwritten(tmp_path):
    destination = tmp_path / 'existing.db'
    destination.write_bytes(b'preserve local edits')
    with pytest.raises(FileExistsError, match='preserve local edits'):
        build_normalized_customers(tmp_path / 'missing', destination, organization_id='org')
    assert destination.read_bytes() == b'preserve local edits'


def test_empty_children_and_non_equivalent_labels(tmp_path):
    customer = {'Customer ID': '1', 'Beat': 'Thirukattupalli', 'Branch': 'Electricals',
                'Jurisdiction': 'TRICHY', 'Payment Terms Label': 'Due end of next month'}
    other = {**customer, 'Customer ID': '2', 'Beat': 'Thirukkattupalli'}
    source = sources(tmp_path, customers=[customer, other], addresses=[], persons=[])
    result = build_normalized_customers(source, tmp_path / 'c.db', organization_id='org')
    report = json.loads(result.report.read_text())
    assert report['counts']['Customer Addresses'] == 0
    assert any('Similar beat names' in issue['reason'] for issue in report['review_issues'])
    db = sqlite3.connect(result.database)
    assert db.execute('SELECT "Payment Terms Label" FROM "Customer Financials" LIMIT 1').fetchone()[0] == 'Due end of next month'
    assert db.execute('SELECT "Contact Persons" FROM Customers LIMIT 1').fetchone()[0] == '[]'
    db.close()


def test_download_uses_cached_metadata_and_exports_all_three(tmp_path):
    from contextlib import contextmanager
    store = Mock()
    store.find_views.side_effect = lambda name: [{'name': name, 'view_id': name}]
    store.get_columns.return_value = [{'name': 'Customer ID'}]
    store.get_info.return_value = '2026-10-27T17:03:36Z'

    @contextmanager
    def cached_store():
        yield store

    catalog = SimpleNamespace(cached_store=cached_store, workspace_id='workspace')
    api = Mock()
    api.views.export_all.return_value = [{'Customer ID': '1'}]
    api.queries.execute.return_value = [{'source_count': '1'}]
    result = download_customer_normalization_sources(api, catalog, tmp_path / 'source', organization_id='org')
    assert api.views.export_all.call_count == 3
    api.metadata.sync_workspace.assert_not_called()
    manifest = json.loads((result / 'manifest.json').read_text())
    assert manifest['organization_id'] == 'org'
    assert manifest['last_metadata_sync'] == '2026-10-27T17:03:36Z'


def test_download_failure_does_not_publish_complete_manifest(tmp_path):
    from contextlib import contextmanager
    store = Mock()
    store.find_views.side_effect = lambda name: [{'name': name, 'view_id': name}]
    store.get_columns.return_value = []

    @contextmanager
    def cached_store():
        yield store

    catalog = SimpleNamespace(cached_store=cached_store, workspace_id='workspace')
    api = Mock()
    api.views.export_all.side_effect = [[{'Customer ID': '1'}], RuntimeError('export failed')]
    destination = tmp_path / 'source'
    with pytest.raises(RuntimeError, match='export failed'):
        download_customer_normalization_sources(api, catalog, destination, organization_id='org')
    assert not (destination / 'manifest.json').exists()


def test_download_rejects_truncated_exports(tmp_path):
    from contextlib import contextmanager
    store = Mock()
    store.find_views.side_effect = lambda name: [{'name': name, 'view_id': name}]
    store.get_columns.return_value = [{'name': 'Customer ID'}]

    @contextmanager
    def cached_store():
        yield store

    catalog = SimpleNamespace(cached_store=cached_store, workspace_id='workspace')
    api = Mock()
    api.views.export_all.return_value = [{'Customer ID': '1'}]
    api.queries.execute.return_value = [{'source_count': '2'}]
    destination = tmp_path / 'source'
    with pytest.raises(ValueError, match='row count differs'):
        download_customer_normalization_sources(api, catalog, destination, organization_id='org')
    assert not destination.exists()


def test_cli_offline_normalization_uses_separate_store(tmp_path, monkeypatch, capsys):
    import sys
    from apps import customer_local_store
    source = sources(tmp_path)
    destination = tmp_path / 'normalized.db'
    monkeypatch.setattr(customer_local_store.Config, 'ORG_ID', 'org')
    monkeypatch.setattr(sys, 'argv', ['customer_local_store.py', 'normalize',
                                    '--source', str(source), '--db', str(destination)])
    customer_local_store.main()
    result = json.loads(capsys.readouterr().out)
    assert result['counts']['Customers'] == 1
    db = sqlite3.connect(destination)
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='customer_snapshots'").fetchone()
    db.close()
