"""Download the Books Sales Person and Beat custom modules into editable SQLite tables."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from zoho.base_resource import BaseResource

MODULES = {'sales_persons': 'cm_user', 'beats': 'cm_beat'}


class ModuleDownloadResult(TypedDict):
    database: str
    counts: dict[str, int]
    synced_at: str


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def module_record_json(db: sqlite3.Connection, *, table: str, record_id: str) -> dict[str, Any]:
    """Reconstruct an editable record with its original JSON types and key presence."""
    if table not in MODULES:
        raise ValueError(f'Unsupported module table: {table}')
    cursor = db.execute(f'SELECT * FROM {_quote(table)} WHERE module_record_id=?', (record_id,))
    values = cursor.fetchone()
    saved = db.execute('SELECT raw_json FROM module_snapshots WHERE table_name=? AND record_id=?',
                       (table, record_id)).fetchone()
    if saved is None and db.execute("SELECT 1 FROM sqlite_master WHERE name='module_local_creates' AND type='table'").fetchone():
        saved = db.execute('SELECT record_json FROM module_local_creates WHERE table_name=? AND record_id=?',
                           (table, record_id)).fetchone()
    if values is None or saved is None:
        raise ValueError(f'Unknown {table} record: {record_id}')
    original = json.loads(saved[0])
    result = {}
    for column, value in zip(cursor.description, values):
        key = column[0]
        if key not in original and value is None:
            continue
        template = original.get(key)
        if value is not None and isinstance(template, (list, dict)):
            value = json.loads(value)
            if type(value) is not type(template):
                raise ValueError(f'{table}.{key} has invalid JSON type')
        elif value is not None and isinstance(template, bool):
            if value not in (0, 1):
                raise ValueError(f'{table}.{key} must be 0 or 1')
            value = bool(value)
        result[key] = value
    return result


def download_books_custom_modules(books: Any, *, database: Path) -> ModuleDownloadResult:
    """Read both modules, then commit a complete organization-scoped local snapshot.

    A refresh refuses to overwrite direct table edits. No cloud mutation methods
    are called. All pages use 200 records and include all statuses.
    """
    downloaded: dict[str, list[dict[str, Any]]] = {}
    for table, module in MODULES.items():
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in range(1, 10001):
            response = BaseResource(books, module).list(params={
                'page': page, 'per_page': 200, 'filter_by': 'Status.All'})
            rows = response.get('module_records')
            context = response.get('page_context', {})
            if (not isinstance(rows, list) or type(context.get('has_more_page')) is not bool
                or context.get('page', page) != page):
                raise ValueError(f'Malformed {module} page {page}; database not updated')
            for row in rows:
                rid = row.get('module_record_id')
                if not isinstance(rid, str) or not rid or rid in seen or row.get('module_api_name') != module:
                    raise ValueError(f'Invalid/duplicate identity in {module} page {page}')
                datetime.fromisoformat(row['last_modified_time'])
                seen.add(rid)
                records.append(row)
            if not context['has_more_page']:
                break
            if not rows:
                raise ValueError(f'Empty intermediate page in {module}')
            time.sleep(1)
        else:
            raise ValueError(f'Pagination limit reached for {module}')
        downloaded[table] = records
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            owner = db.execute("SELECT value FROM metadata WHERE key='organization_id'").fetchone()
            if owner and owner[0] != str(books.organization_id):
                raise ValueError('Database belongs to another Books organization')
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)',
                       ('organization_id', str(books.organization_id)))
            db.execute('''CREATE TABLE IF NOT EXISTS module_snapshots (
                table_name TEXT,record_id TEXT,raw_json TEXT NOT NULL,
                PRIMARY KEY(table_name,record_id))''')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_local_creates'").fetchone():
                if db.execute('SELECT 1 FROM module_local_creates LIMIT 1').fetchone():
                    raise ValueError('Local rows changed: pending module creations; refresh refused')
            # Validate both tables before replacing any data.
            for table in MODULES:
                old = db.execute('SELECT record_id,raw_json FROM module_snapshots WHERE table_name=?',
                                 (table,)).fetchall()
                if old:
                    ids = {r[0] for r in db.execute(f'SELECT module_record_id FROM {_quote(table)}')}
                    if ids != {r[0] for r in old}:
                        raise ValueError(f'Local rows changed in {table}; refresh refused')
                    for rid, raw in old:
                        if module_record_json(db, table=table, record_id=rid) != json.loads(raw):
                            raise ValueError(f'Local edits in {table}/{rid}; refresh refused')
            for table, rows in downloaded.items():
                db.execute(f'CREATE TABLE IF NOT EXISTS {_quote(table)} (module_record_id TEXT PRIMARY KEY)')
                columns = {r[1] for r in db.execute(f'PRAGMA table_info({_quote(table)})')}
                for row in rows:
                    for key in row:
                        if key not in columns:
                            if key.casefold() in {c.casefold() for c in columns}:
                                raise ValueError(f'Conflicting JSON column: {key}')
                            db.execute(f'ALTER TABLE {_quote(table)} ADD COLUMN {_quote(key)}')
                            columns.add(key)
                db.execute(f'DELETE FROM {_quote(table)}')
                db.execute('DELETE FROM module_snapshots WHERE table_name=?', (table,))
                for row in rows:
                    values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                              else int(v) if isinstance(v, bool) else v for v in row.values()]
                    cols = ','.join(_quote(k) for k in row)
                    placeholders = ','.join('?' for _ in row)
                    db.execute(f'INSERT INTO {_quote(table)} ({cols}) VALUES ({placeholders})', values)
                    db.execute('INSERT INTO module_snapshots VALUES (?,?,?)',
                               (table, row['module_record_id'], json.dumps(row, ensure_ascii=False)))
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',
                           (table + '_synced_at', stamp))
    finally:
        db.close()
    return {'database': str(database), 'counts': {k: len(v) for k, v in downloaded.items()},
            'synced_at': stamp}


def stage_new_beat(database: Path, *, name: str) -> dict[str, Any]:
    """Create a local-only beat; its temporary ID must never be sent as a Books ID."""
    from uuid import uuid4

    name = name.strip()
    if not name:
        raise ValueError('Beat name is required')
    db = sqlite3.connect(database)
    try:
        with db:
            existing = {r[1] for r in db.execute('PRAGMA table_info(beats)')}
            for key in ('module_api_name', 'module_record_id', 'record_name', 'cf_beat_id',
                        'cf_beat_id_formatted', 'cf_beat_name', 'cf_beat_name_formatted'):
                if key not in existing:
                    db.execute(f'ALTER TABLE beats ADD COLUMN {_quote(key)}')
            if db.execute('SELECT 1 FROM beats WHERE lower(trim(cf_beat_name))=lower(?)', (name,)).fetchone():
                raise ValueError(f'Beat already exists: {name}')
            db.execute('''CREATE TABLE IF NOT EXISTS module_local_creates (
                table_name TEXT NOT NULL,record_id TEXT NOT NULL,record_json TEXT NOT NULL,
                created_at TEXT NOT NULL,PRIMARY KEY(table_name,record_id))''')
            numbers = [int(r[0]) for r in db.execute('SELECT cf_beat_id FROM beats')
                       if str(r[0]).isdigit()]
            beat_number = str(max(numbers, default=0) + 1).zfill(5)
            record = {'module_api_name': 'cm_beat', 'module_record_id': 'local:' + str(uuid4()),
                      'record_name': beat_number, 'cf_beat_id': beat_number,
                      'cf_beat_id_formatted': beat_number, 'cf_beat_name': name,
                      'cf_beat_name_formatted': name}
            columns = ','.join(_quote(k) for k in record)
            marks = ','.join('?' for _ in record)
            db.execute(f'INSERT INTO beats ({columns}) VALUES ({marks})', list(record.values()))
            db.execute('INSERT INTO module_local_creates VALUES (?,?,?,?)',
                       ('beats', record['module_record_id'], json.dumps(record),
                        datetime.now(timezone.utc).isoformat()))
        return record
    finally:
        db.close()
