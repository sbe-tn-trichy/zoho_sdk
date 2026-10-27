import json
import sqlite3
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from workflows.books_custom_module_store import download_books_custom_modules, module_record_json


def record(module, rid='001'):
    return {'module_api_name': module, 'module_record_id': rid, 'record_name': '0001',
            'last_modified_time': '2026-10-27T10:00:00+0530', 'is_locked': False,
            'nested': {'x': [1, True, None]}, 'number': 12.5}


def page(rows, more=False, number=1):
    return {'module_records': rows, 'page_context': {'page': number, 'has_more_page': more}}


def api(*responses, org='org'):
    return SimpleNamespace(organization_id=org, request=Mock(side_effect=responses))


def test_download_roundtrip_and_protect_local_edits(tmp_path):
    path = tmp_path / 'modules.sqlite3'
    rows = [record('cm_user'), record('cm_beat')]
    b = api(page([rows[0]]), page([rows[1]]))
    assert download_books_custom_modules(b, database=path)['counts'] == {'sales_persons': 1, 'beats': 1}
    assert b.request.call_args_list[0].args == ('GET', 'cm_user')
    assert b.request.call_args_list[0].kwargs['params']['per_page'] == 200
    db = sqlite3.connect(path)
    for table, row in zip(['sales_persons', 'beats'], rows):
        assert module_record_json(db, table=table, record_id='001') == row
    db.execute("UPDATE beats SET record_name='Edited'")
    db.commit()
    with pytest.raises(ValueError, match='Local edits'):
        download_books_custom_modules(api(page([rows[0]]), page([rows[1]])), database=path)
    assert db.execute('SELECT record_name FROM beats').fetchone()[0] == 'Edited'
    db.close()


def test_pagination_and_empty_module(tmp_path, monkeypatch):
    monkeypatch.setattr('workflows.books_custom_module_store.time.sleep', lambda _: None)
    b = api(page([record('cm_user')], True), page([record('cm_user', '002')], number=2), page([]))
    result = download_books_custom_modules(b, database=tmp_path / 'm.db')
    assert result['counts'] == {'sales_persons': 2, 'beats': 0}
    assert b.request.call_args_list[1].kwargs['params']['page'] == 2


@pytest.mark.parametrize('bad', [page([record('wrong')]), {'module_records': []},
                                    page([record('cm_user'), record('cm_user')])])
def test_bad_page_does_not_create_database(tmp_path, bad):
    path = tmp_path / 'm.db'
    with pytest.raises(ValueError):
        download_books_custom_modules(api(bad), database=path)
    assert not path.exists()


def test_organization_guard(tmp_path):
    path = tmp_path / 'm.db'
    download_books_custom_modules(api(page([]), page([])), database=path)
    with pytest.raises(ValueError, match='another Books organization'):
        download_books_custom_modules(api(page([]), page([]), org='other'), database=path)


def test_local_beat_creation(tmp_path):
    from workflows.books_custom_module_store import stage_new_beat
    path = tmp_path / 'm.db'
    download_books_custom_modules(api(page([]), page([record('cm_beat')])), database=path)
    row = stage_new_beat(path, name='Recovery - Abu')
    assert row['module_record_id'].startswith('local:')
    db = sqlite3.connect(path)
    assert module_record_json(db, table='beats', record_id=row['module_record_id']) == row
    assert db.execute('SELECT count(*) FROM module_snapshots').fetchone()[0] == 1
    with pytest.raises(ValueError, match='already exists'):
        stage_new_beat(path, name='Recovery - Abu')
    with pytest.raises(ValueError, match='Local rows changed'):
        download_books_custom_modules(api(page([]), page([record('cm_beat')])), database=path)
