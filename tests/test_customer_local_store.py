import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from workflows.customer_local_store import open_store, sync_customers, stage_mobile_plan, export_pending

STAMP = '2026-10-27T10:00:00+05:30'


def contact(cid='1', stamp=STAMP):
    return dict(contact_id=cid, contact_name='Customer', contact_type='customer',
                status='active', last_modified_time=stamp, phone='9876543210', mobile='')


def client(*pages):
    return SimpleNamespace(contacts=SimpleNamespace(list=Mock(side_effect=pages)))


def page(rows, more=False):
    return {'contacts': rows, 'page_context': {'has_more_page': more}}


def test_pages_and_incremental_preserve_edits(tmp_path):
    db = open_store(tmp_path / 'c.db', organization_id='org')
    api = client(page([contact()], True), page([contact('2')]))
    assert sync_customers(db, api, request_delay=0) == dict(pages=2, customers=2, changed=2)
    assert api.contacts.list.call_args_list[0].kwargs['params']['per_page'] == 200
    assert api.contacts.list.call_args_list[1].kwargs['params']['page'] == 2
    db.execute("UPDATE customer_snapshots SET local_json='{}', edit_base_time=? WHERE contact_id='1'", (STAMP,))
    db.commit()
    assert sync_customers(db, client(page([contact(), contact('2')])))['changed'] == 0
    assert db.execute("SELECT conflict FROM customer_snapshots WHERE contact_id='1'").fetchone()[0] == 0
    newer = '2026-10-27T11:00:00+05:30'
    sync_customers(db, client(page([contact(stamp=newer)])))
    row = db.execute("SELECT * FROM customer_snapshots WHERE contact_id='1'").fetchone()
    assert row['conflict'] == 1 and row['local_json'] == '{}'
    assert db.execute("SELECT present_in_cloud FROM customer_snapshots WHERE contact_id='2'").fetchone()[0] == 0
    with pytest.raises(ValueError, match='different'):
        open_store(tmp_path / 'c.db', organization_id='other')


@pytest.mark.parametrize('bad', [page([contact()]), {'contacts': []}, page([], True)])
def test_failed_scan_not_committed(tmp_path, bad):
    db = open_store(tmp_path / 'c.db', organization_id='org')
    with pytest.raises((ValueError, StopIteration)):
        sync_customers(db, client(page([contact()], True), bad), request_delay=0)
    assert db.execute('SELECT count(*) FROM customer_snapshots').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM sync_runs').fetchone()[0] == 0


def test_stage_and_export_and_stale_rollback(tmp_path):
    db = open_store(tmp_path / 'c.db', organization_id='org')
    sync_customers(db, client(page([contact()])))
    detail = {**contact(), 'contact_persons': [dict(contact_person_id='p', phone='9876543210', mobile='')]}
    snapshot = tmp_path / 'before.json'
    snapshot.write_text(json.dumps({'contact': detail}))
    entry = dict(contact_id='1', last_modified_time=STAMP, primary_contact_id='p', before_file=str(snapshot))
    plan = tmp_path / 'plan.json'
    data = dict(summary={'complete': True}, review=[], failures=[], ready=[entry])
    plan.write_text(json.dumps(data))
    assert stage_mobile_plan(db, plan)['staged'] == 1
    assert stage_mobile_plan(db, plan)['staged'] == 1
    output = tmp_path / 'pending.json'
    assert export_pending(db, output) == dict(pending=1, conflicts=0)
    staged = json.loads(output.read_text())['customers'][0]
    assert staged['before']['phone'] == '9876543210'
    assert staged['after']['phone'] == ''
    assert staged['after']['mobile'] == '9876543210'
    assert staged['after']['contact_persons'][0]['phone'] == ''
    entry['last_modified_time'] = 'old'
    plan.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='modification time'):
        stage_mobile_plan(db, plan)
    assert json.loads(db.execute('SELECT cloud_json FROM customer_snapshots').fetchone()[0])['phone'] == '9876543210'


def test_export_keeps_edit_baseline_after_cloud_change(tmp_path):
    db = open_store(tmp_path / 'c.db', organization_id='org')
    sync_customers(db, client(page([contact()])))
    baseline = json.dumps(contact())
    db.execute('UPDATE customer_snapshots SET edit_base_json=?,edit_base_time=?,local_json=?,detail_json=?',
               (baseline, STAMP, '{}', baseline))
    db.commit()
    sync_customers(db, client(page([contact(stamp='2026-10-27T12:00:00+05:30')])))
    output = tmp_path / 'pending.json'
    assert export_pending(db, output)['conflicts'] == 1
    row = json.loads(output.read_text())['customers'][0]
    assert row['before']['last_modified_time'] == STAMP
    assert row['after'] == {}
    assert db.execute('SELECT detail_json FROM customer_snapshots').fetchone()[0] is None


def test_editable_columns_roundtrip_and_sync_conflict(tmp_path):
    from workflows.customer_table import customer_json
    db = open_store(tmp_path / 'c.db', organization_id='org')
    original = {**contact(), 'active_flag': True, 'empty_object': {}, 'empty_list': [],
                'nullable': None, 'credit': '12.30', 'billing_address': {'address': ', Test, '},
                'custom_fields': [{'api_name': 'cf_type', 'value': 'Dealer'}]}
    sync_customers(db, client(page([original, contact('2')])))
    assert customer_json(db, '1') == original
    assert 'billing_address' not in customer_json(db, '2')
    db.execute("UPDATE customers SET phone='',mobile='9876543210' WHERE contact_id='1'")
    db.commit()
    export_pending(db, tmp_path / 'pending.json')
    assert customer_json(db, '1')['phone'] == ''
    sync_customers(db, client(page([{**original, 'last_modified_time': '2026-10-28T10:00:00+05:30'}, contact('2')])))
    row = db.execute("SELECT * FROM customer_snapshots WHERE contact_id='1'").fetchone()
    assert row['conflict'] == 1
    assert json.loads(row['edit_base_json']) == original
    assert customer_json(db, '1')['mobile'] == '9876543210'


def test_legacy_migration_backup_and_roundtrip(tmp_path):
    from workflows.customer_table import customer_json
    path = tmp_path / 'c.db'
    db = open_store(path, organization_id='org')
    original = {**contact(), 'is_portal_enabled': False, 'tags': []}
    sync_customers(db, client(page([original])))
    db.execute('DROP TABLE customers')
    db.execute('DROP TABLE customer_record_shapes')
    db.execute('ALTER TABLE customer_snapshots RENAME TO customers')
    db.commit()
    db.close()
    db = open_store(path, organization_id='org')
    assert customer_json(db, '1') == original
    assert db.execute('SELECT count(*) FROM customer_review').fetchone()[0] == 1
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    db.close()
    db = open_store(path, organization_id='org')
    assert customer_json(db, '1') == original
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1


def test_invalid_json_and_identity_edits_rejected(tmp_path):
    from workflows.customer_table import customer_json
    db = open_store(tmp_path / 'c.db', organization_id='org')
    sync_customers(db, client(page([{**contact(), 'tags': [], 'enabled': True}])))
    db.execute("UPDATE customers SET tags='{}'")
    db.commit()
    with pytest.raises(ValueError, match='JSON list'):
        customer_json(db, '1')
    db.execute("UPDATE customers SET tags='[]',last_modified_time='edited'")
    db.commit()
    with pytest.raises(ValueError, match='metadata'):
        export_pending(db, tmp_path / 'p.json')
    assert db.execute('SELECT local_json FROM customer_snapshots').fetchone()[0] is None


def test_compact_constants_roundtrip_and_promote_changed_field(tmp_path):
    from workflows.customer_table import compact_customer_columns, customer_json
    db = open_store(tmp_path/'c.db', organization_id='org')
    original = [{**contact(str(i)), 'flag': False, 'nullable': None, 'nested': [],
                 'varying_type': 0 if i == 1 else 0.0} for i in (1, 2)]
    sync_customers(db, client(page(original)))
    with db:
        result = compact_customer_columns(db)
    columns = {r[1] for r in db.execute('PRAGMA table_info(customers)')}
    assert 'contact_id' in columns and 'contact_type' not in columns
    assert 'varying_type' in columns
    assert 'flag' in result['moved_columns']
    assert db.execute('SELECT count(*) FROM customer_constants').fetchone()[0] == 1
    for row in original:
        assert customer_json(db, row['contact_id']) == row
    db.execute("UPDATE customers SET varying_type=4 WHERE contact_id='1'")
    db.commit()
    original[1]['flag'] = True
    sync_customers(db, client(page(original)))
    assert 'flag' in {r[1] for r in db.execute('PRAGMA table_info(customers)')}
    assert customer_json(db, '1')['varying_type'] == 4
    assert customer_json(db, '2')['flag'] is True
    assert db.execute('SELECT count(*) FROM customers_full').fetchone()[0] == 2
    with db:
        compact_customer_columns(db)
    assert customer_json(db, '2')['flag'] is True


def test_compact_preserves_missing_vs_null(tmp_path):
    from workflows.customer_table import compact_customer_columns, customer_json
    db = open_store(tmp_path/'c.db', organization_id='org')
    sync_customers(db, client(page([{**contact(), 'optional': None}, contact('2')])))
    with db:
        compact_customer_columns(db)
    assert customer_json(db,'1')['optional'] is None
    assert 'optional' not in customer_json(db,'2')
