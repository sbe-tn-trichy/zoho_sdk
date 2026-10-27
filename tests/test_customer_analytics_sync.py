import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from workflows.customer_analytics_sync import sync_analytics_customers
from workflows.customer_normalization import SOURCE_NAMES, build_normalized_customers


def source(tmp_path, name, *, customers=None, addresses=None, persons=None, organization='org', workspace='workspace'):
    directory = tmp_path / name
    directory.mkdir()
    customers = customers if customers is not None else [
        {'Customer ID': '1', 'Customer Name': 'Shop', 'Phone': '123-456-7890',
         'Credit Limit': '123.00', 'Beat': 'North', 'Payment Terms Label': 'Due On Receipt'},
        {'Customer ID': '2', 'Customer Name': 'Other', 'Phone': '',
         'Credit Limit': '0.00', 'Beat': '', 'Payment Terms Label': 'Net 30'},
    ]
    addresses = addresses if addresses is not None else [
        {'Address ID': '10', 'Customer ID': '1', 'Billing City': 'City', 'Shipping Code': '001234'}]
    persons = persons if persons is not None else [
        {'Contact Person ID': '20', 'Customer ID': '1', 'Phone': '1234567890', 'Email': 'a@example.com'}]
    data = {'customers': customers, 'addresses': addresses, 'contact_persons': persons}
    manifest = {'organization_id': organization, 'workspace_id': workspace,
                'last_metadata_sync': '2026-10-27T17:03:36Z', 'captured_at': name, 'views': {}}
    for key, rows in data.items():
        columns = list(rows[0]) if rows else (
            ['Address ID', 'Customer ID', 'Billing City', 'Shipping Code'] if key == 'addresses'
            else ['Contact Person ID', 'Customer ID', 'Phone', 'Email'])
        manifest['views'][key] = {'name': SOURCE_NAMES[key], 'view_id': key, 'rows': len(rows), 'columns': columns}
        (directory / f'{key}.json').write_text(json.dumps(rows), encoding='utf-8')
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return directory


def sync(path, export, *, organization='org', workspace='workspace'):
    return sync_analytics_customers(None, SimpleNamespace(workspace_id=workspace), path,
                                    organization_id=organization, source=export)


def read(path, table='Customers', rid='1'):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    key = 'Address ID' if table == 'Customer Addresses' else 'Customer ID'
    result = dict(db.execute(f'SELECT * FROM "{table}" WHERE "{key}"=?', (rid,)).fetchone())
    db.close()
    return result


def edit(path, sql, parameters=()):
    with sqlite3.connect(path) as db:
        db.execute(sql, parameters)


def test_create_repeat_updates_and_backup(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    first = sync(path, export)
    assert first.added['Customers'] == 2 and first.backup is None
    assert read(path)['Phone'] == '1234567890'
    repeated = sync(path, export)
    assert not any(repeated.added.values()) and not any(repeated.updated.values())
    assert repeated.conflicts == 0 and repeated.backup.is_file()
    assert read(repeated.backup) == read(path) | {'_sync_info_json': read(repeated.backup)['_sync_info_json']}
    changed = json.loads((export / 'customers.json').read_text())
    changed[0]['Customer Name'] = 'New name'
    changed[0]['Credit Limit'] = '456.00'
    second = sync(path, source(tmp_path, 'second', customers=changed))
    assert second.updated['Customers'] == 1 and second.updated['Customer Financials'] == 1
    assert read(path)['Customer Name'] == 'New name'
    assert read(path, 'Customer Financials')['Credit Limit'] == '456.00'


def test_local_edits_survive_and_conflicts_persist_until_convergence(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    edit(path, 'UPDATE Customers SET Phone=? WHERE "Customer ID"=?', ('9999999999', '1'))
    kept = sync(path, export)
    assert kept.preserved_local_fields == 1 and kept.conflicts == 0
    changed = json.loads((export / 'customers.json').read_text())
    changed[0]['Phone'] = '8888888888'
    changed_export = source(tmp_path, 'changed', customers=changed)
    conflicted = sync(path, changed_export)
    assert conflicted.conflicts == 1 and read(path)['Phone'] == '9999999999'
    assert sync(path, changed_export).conflicts == 1
    edit(path, 'UPDATE Customers SET Phone=? WHERE "Customer ID"=?', ('8888888888', '1'))
    assert sync(path, changed_export).conflicts == 0
    assert json.loads(read(path)['_sync_conflicts_json']) == []


def test_secondary_contacts_merge_by_identity_and_field(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    persons = json.loads(read(path)['Contact Persons'])
    persons[0]['Phone'] = '9999999999'
    edit(path, 'UPDATE Customers SET "Contact Persons"=? WHERE "Customer ID"=?', (json.dumps(persons), '1'))
    incoming = [{**persons[0], 'Phone': '1234567890', 'Email': 'new@example.com'},
                {'Contact Person ID': '21', 'Customer ID': '1', 'Phone': '7777777777', 'Email': 'b@example.com'}]
    result = sync(path, source(tmp_path, 'second', persons=incoming))
    assert result.conflicts == 0 and result.preserved_local_fields == 1
    merged = json.loads(read(path)['Contact Persons'])
    assert merged[0]['Phone'] == '9999999999' and merged[0]['Email'] == 'new@example.com'
    assert merged[1]['Contact Person ID'] == '21'


def test_deleted_source_records_retained_and_reappearance_reconciled(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    customers = json.loads((export / 'customers.json').read_text())[:1]
    deleted = sync(path, source(tmp_path, 'deleted', customers=customers, addresses=[], persons=[]))
    assert deleted.counts['Customers'] == 2 and deleted.missing_from_analytics['Customers'] == 1
    assert read(path, rid='2')['_present_in_analytics'] == 0
    assert read(path, 'Customer Addresses', '10')['_present_in_analytics'] == 0
    assert len(json.loads(read(path)['Contact Persons'])) == 1
    assert deleted.conflicts >= 3
    restored = sync(path, export)
    assert restored.conflicts == 0 and not any(restored.missing_from_analytics.values())
    assert read(path, rid='2')['_present_in_analytics'] == 1


@pytest.mark.parametrize('operation', ['delete', 'identity', 'owner', 'contact_ids'])
def test_direct_identity_edits_fail_without_overwrite(tmp_path, operation):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    if operation == 'delete':
        edit(path, 'DELETE FROM "Customer Beat" WHERE "Customer ID"=\'2\'')
    elif operation == 'identity':
        edit(path, 'UPDATE "Customer Addresses" SET "Address ID"=\'11\'')
    elif operation == 'owner':
        edit(path, 'UPDATE "Customer Addresses" SET "Customer ID"=\'2\'')
    else:
        edit(path, 'UPDATE Customers SET "Contact Persons"=\'[]\' WHERE "Customer ID"=\'1\'')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='restore|edited'):
        sync(path, export)
    assert path.read_bytes() == before


@pytest.mark.parametrize('changed_scope', ['org', 'workspace'])
def test_scope_mismatch_leaves_database_unchanged(tmp_path, changed_scope):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    before = path.read_bytes()
    export = source(tmp_path, 'other', organization='other' if changed_scope == 'org' else 'org',
                    workspace='other' if changed_scope == 'workspace' else 'workspace')
    with pytest.raises(ValueError, match='another|different'):
        sync(path, export)
    assert path.read_bytes() == before


def test_upgrade_original_snapshot_preserves_existing_cleanup_edits(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    build_normalized_customers(export, path, organization_id='org')
    edit(path, 'UPDATE "Customer Beat" SET Beat=\'Reviewed beat\' WHERE "Customer ID"=\'1\'')
    result = sync(path, export)
    assert read(path, 'Customer Beat')['Beat'] == 'Reviewed beat'
    assert result.preserved_local_fields == 1 and result.backup.is_file()
    assert json.loads(read(path)['_sync_info_json'])['organization_id'] == 'org'


def test_late_error_rolls_back_all_four_tables(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    customers = json.loads((export / 'customers.json').read_text())
    customers[0]['Customer Name'] = 'Must roll back'
    addresses = json.loads((export / 'addresses.json').read_text())
    addresses[0]['Customer ID'] = '2'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='ownership changed'):
        sync(path, source(tmp_path, 'second', customers=customers, addresses=addresses))
    assert path.read_bytes() == before
    assert read(path)['Customer Name'] == 'Shop'


def test_contact_ownership_change_is_rejected(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    persons = json.loads((export / 'contact_persons.json').read_text())
    persons[0]['Customer ID'] = '2'
    with pytest.raises(ValueError, match='ownership changed'):
        sync(path, source(tmp_path, 'second', persons=persons))
    assert json.loads(read(path)['Contact Persons'])[0]['Customer ID'] == '1'


def test_added_column_and_customer_are_synced(tmp_path):
    export = source(tmp_path, 'first')
    path = tmp_path / 'customers.db'
    sync(path, export)
    customers = json.loads((export / 'customers.json').read_text())
    for customer in customers:
        customer['New Attribute'] = 'new'
    customers.append({**customers[0], 'Customer ID': '3'})
    result = sync(path, source(tmp_path, 'second', customers=customers))
    assert result.added['Customers'] == 1 and result.added['Customer Beat'] == 1
    assert read(path, rid='3')['New Attribute'] == 'new'
    assert sync(path, source(tmp_path, 'third', customers=customers)).conflicts == 0


def test_cli_offline_sync_repeats(tmp_path, monkeypatch, capsys):
    from apps import sync_analytics_customers as app
    import sys
    export = source(tmp_path, 'first')
    destination = tmp_path / 'customers.db'
    monkeypatch.setattr(app.Config, 'ORG_ID', 'org')
    monkeypatch.setattr(sys, 'argv', ['sync_analytics_customers.py', '--db', str(destination),
                                    '--workspace-id', 'workspace', '--source', str(export)])
    app.main()
    assert json.loads(capsys.readouterr().out)['added']['Customers'] == 2
    app.main()
    assert not any(json.loads(capsys.readouterr().out)['updated'].values())


def test_contact_export_order_is_not_a_business_update(tmp_path):
    persons = [{'Contact Person ID': '20', 'Customer ID': '1', 'Phone': '1234567890', 'Email': ''},
               {'Contact Person ID': '21', 'Customer ID': '1', 'Phone': '2345678901', 'Email': ''}]
    path = tmp_path / 'customers.db'
    sync(path, source(tmp_path, 'first', persons=persons))
    result = sync(path, source(tmp_path, 'reordered', persons=list(reversed(persons))))
    assert result.updated['Customers'] == 0
    assert [p['Contact Person ID'] for p in json.loads(read(path)['Contact Persons'])] == ['20', '21']
    assert [p['Contact Person ID'] for p in json.loads(read(path)['_source_contact_persons_json'])] == ['21', '20']


def test_valid_other_scope_exports_cannot_overwrite_existing_store(tmp_path):
    path = tmp_path / 'customers.db'
    sync(path, source(tmp_path, 'first'))
    before = path.read_bytes()
    export = source(tmp_path, 'other', organization='other', workspace='other')
    with pytest.raises(ValueError, match='another organization'):
        sync(path, export, organization='other', workspace='other')
    assert path.read_bytes() == before
