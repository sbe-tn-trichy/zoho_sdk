"""Editable columns with exact JSON names and lossless JSON reconstruction."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def effective_record(row: sqlite3.Row) -> dict[str, Any]:
    record = json.loads(row['cloud_json'])
    record.update(json.loads(row['detail_json'] or '{}'))
    record.update(json.loads(row['local_json'] or '{}'))
    return record


def materialize_customers(db: sqlite3.Connection) -> None:
    """Populate editable columns from snapshots after a successful local operation."""
    _expand_constants(db)
    db.execute('CREATE TABLE IF NOT EXISTS customers (contact_id TEXT PRIMARY KEY)')
    db.execute('''CREATE TABLE IF NOT EXISTS customer_record_shapes (
        contact_id TEXT PRIMARY KEY, shape_json TEXT NOT NULL)''')
    rows = db.execute('SELECT * FROM customer_snapshots').fetchall()
    records = [effective_record(r) for r in rows]
    existing = {r[1] for r in db.execute('PRAGMA table_info(customers)')}
    for record in records:
        for key in record:
            if key not in existing:
                if key.casefold() in {k.casefold() for k in existing}:
                    raise ValueError(f'JSON keys collide in SQLite: {key}')
                # No affinity avoids coercing string IDs, numeric strings or mixed types.
                db.execute(f'ALTER TABLE customers ADD COLUMN {_quote(key)}')
                existing.add(key)
    for record in records:
        shape = {k: type(v).__name__ for k, v in record.items()}
        values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                  else int(v) if isinstance(v, bool) else v for v in record.values()]
        columns = ','.join(_quote(k) for k in record)
        marks = ','.join('?' for _ in record)
        db.execute('DELETE FROM customers WHERE contact_id=?', (record['contact_id'],))
        db.execute(f'INSERT INTO customers ({columns}) VALUES ({marks})', values)
        db.execute('INSERT OR REPLACE INTO customer_record_shapes VALUES (?,?)',
                   (record['contact_id'], json.dumps(shape)))

    if db.execute("SELECT 1 FROM metadata WHERE key='compact_customer_columns' AND value='true'").fetchone():
        compact_customer_columns(db)


def customer_json(db: sqlite3.Connection, contact_id: str) -> dict[str, Any]:
    """Reconstruct current editable values, preserving booleans, arrays and missing keys."""
    row = db.execute('SELECT * FROM customers WHERE contact_id=?', (contact_id,)).fetchone()
    shape_row = db.execute('SELECT shape_json FROM customer_record_shapes WHERE contact_id=?',
                           (contact_id,)).fetchone()
    if row is None or shape_row is None:
        raise ValueError(f'Unknown customer: {contact_id}')
    shape = json.loads(shape_row[0])
    result = {}
    values = {**dict(row), **_constant_values(db)}
    for key, value in values.items():
        if key not in shape and value is None:
            continue
        kind = shape.get(key)
        if value is not None and kind in ('dict', 'list'):
            value = json.loads(value)
            if not isinstance(value, dict if kind == 'dict' else list):
                raise ValueError(f'{contact_id}.{key} must remain a JSON {kind}')
        elif value is not None and kind == 'bool':
            if value not in (0, 1):
                raise ValueError(f'{contact_id}.{key} must be 0 or 1')
            value = bool(value)
        result[key] = value
    return result


def capture_table_edits(db: sqlite3.Connection) -> None:
    """Checkpoint direct SQL edits before syncing or exporting; never change cloud copies."""
    rows = db.execute('SELECT * FROM customer_snapshots').fetchall()
    ids = {r['contact_id'] for r in rows}
    table_ids = {r[0] for r in db.execute('SELECT contact_id FROM customers')}
    if ids != table_ids:
        raise ValueError('Customer IDs/rows were changed directly; restore them before continuing')
    for row in rows:
        edited = customer_json(db, row['contact_id'])
        expected = effective_record(row)
        if edited == expected:
            continue
        for key in ('contact_id', 'contact_type', 'last_modified_time'):
            if edited.get(key) != expected.get(key):
                raise ValueError(f'{key} is sync identity metadata and cannot be edited')
        baseline = json.dumps(expected, ensure_ascii=False)
        db.execute('''UPDATE customer_snapshots SET
            edit_base_json=COALESCE(edit_base_json,?),
            edit_base_time=COALESCE(edit_base_time,last_modified_time), local_json=?
            WHERE contact_id=?''', (baseline, json.dumps(edited, ensure_ascii=False), row['contact_id']))


def _constant_values(db: sqlite3.Connection) -> dict[str, Any]:
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_constants'").fetchone()
    if not exists:
        return {}
    rows = db.execute('SELECT * FROM customer_constants').fetchall()
    if len(rows) != 1:
        raise ValueError('customer_constants must contain exactly one row')
    return dict(rows[0])


def _expand_constants(db: sqlite3.Connection) -> None:
    """Restore fields before rebuilding from fresh snapshots; never discard edits."""
    values = _constant_values(db)
    db.execute('DROP VIEW IF EXISTS customers_full')
    for key, value in values.items():
        db.execute(f'ALTER TABLE customers ADD COLUMN {_quote(key)}')
        db.execute(f'UPDATE customers SET {_quote(key)}=?', (value,))
    if values:
        db.execute('DROP TABLE customer_constants')


def compact_customer_columns(db: sqlite3.Connection) -> dict[str, Any]:
    """Move uniform columns into a singleton table, retaining exact JSON field names."""
    if not db.in_transaction:
        db.execute('BEGIN')
    capture_table_edits(db)
    _expand_constants(db)
    count = db.execute('SELECT count(*) FROM customers').fetchone()[0]
    constants: dict[str, Any] = {}
    if count:
        for row in db.execute('PRAGMA table_info(customers)').fetchall():
            key = row[1]
            if key == 'contact_id':
                continue
            quoted = _quote(key)
            values = db.execute(f'SELECT {quoted},typeof({quoted}) FROM customers '
                                f'GROUP BY {quoted},typeof({quoted}) LIMIT 2').fetchall()
            if len(values) == 1:
                constants[key] = values[0][0]
    if constants:
        columns = ','.join(_quote(key) for key in constants)
        db.execute(f'CREATE TABLE customer_constants ({columns})')
        marks = ','.join('?' for _ in constants)
        db.execute(f'INSERT INTO customer_constants VALUES ({marks})', list(constants.values()))
        db.execute('''CREATE TRIGGER customer_constants_single_row BEFORE INSERT ON customer_constants
            WHEN EXISTS(SELECT 1 FROM customer_constants)
            BEGIN SELECT RAISE(ABORT,'customer_constants permits only one row'); END''')
        for key in constants:
            db.execute(f'ALTER TABLE customers DROP COLUMN {_quote(key)}')
        db.execute('CREATE VIEW customers_full AS SELECT c.*,k.* FROM customers c CROSS JOIN customer_constants k')
    else:
        db.execute('CREATE VIEW customers_full AS SELECT * FROM customers')
    db.execute("INSERT OR REPLACE INTO metadata VALUES ('compact_customer_columns','true')")
    return {'customers': count, 'moved_columns': list(constants),
            'customer_columns': len(db.execute('PRAGMA table_info(customers)').fetchall())}
