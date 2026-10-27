"""Local Books customer mirror and reviewed edits. Never writes to Books."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .customer_table import _expand_constants, capture_table_edits, materialize_customers


def open_store(path: Path, *, organization_id: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
        owner = db.execute("SELECT value FROM metadata WHERE key='organization_id'").fetchone()
        if owner and owner[0] != organization_id:
            db.close()
            raise ValueError('Database belongs to a different Books organization')
    legacy = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers'").fetchone()
    if legacy and 'cloud_json' in {r[1] for r in db.execute('PRAGMA table_info(customers)')}:
        backup_dir = path.parent / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / ('customers_before_columns_' +
                                   datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        backup = sqlite3.connect(backup_path)
        try:
            db.backup(backup)
        finally:
            backup.close()
        db.execute('ALTER TABLE customers RENAME TO customer_snapshots')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS customer_snapshots (
            contact_id TEXT PRIMARY KEY, contact_name TEXT NOT NULL,
            status TEXT NOT NULL, last_modified_time TEXT NOT NULL,
            cloud_json TEXT NOT NULL, detail_json TEXT,
            local_json TEXT, edit_base_json TEXT, edit_base_time TEXT, conflict INTEGER NOT NULL DEFAULT 0,
            present_in_cloud INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY, completed_at TEXT NOT NULL,
            pages INTEGER NOT NULL, customers INTEGER NOT NULL, changed INTEGER NOT NULL);
    ''')
    if 'edit_base_json' not in {r[1] for r in db.execute('PRAGMA table_info(customer_snapshots)')}:
        db.execute('ALTER TABLE customer_snapshots ADD COLUMN edit_base_json TEXT')
        db.execute('UPDATE customer_snapshots SET edit_base_json=detail_json WHERE local_json IS NOT NULL')
    db.executescript("""
        CREATE VIEW IF NOT EXISTS customer_review AS SELECT
            contact_id,contact_name,status,last_modified_time,present_in_cloud,conflict,
            json_extract(cloud_json,'$.phone') AS cloud_phone,
            json_extract(cloud_json,'$.mobile') AS cloud_mobile,
            json_extract(local_json,'$.phone') AS local_phone,
            json_extract(local_json,'$.mobile') AS local_mobile,
            local_json IS NOT NULL AS has_local_changes
        FROM customer_snapshots;
    """)
    row = db.execute("SELECT value FROM metadata WHERE key='organization_id'").fetchone()
    if row and row[0] != organization_id:
        db.close()
        raise ValueError('Database belongs to a different Books organization')
    db.execute("INSERT OR IGNORE INTO metadata VALUES ('organization_id', ?)", (organization_id,))
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customers'").fetchone():
        with db:
            materialize_customers(db)
    db.commit()
    return db


def sync_customers(db: sqlite3.Connection, books: Any, *, request_delay: float = 1.0) -> dict[str, int]:
    """Scan all list pages; compare modification times locally, preserving edits.

    Full list scans detect inactive/missing records without relying on an
    unverified server-side modification filter. Commit only complete scans.
    """
    with db:
        capture_table_edits(db)
    records: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        response = books.contacts.list(params={
            'filter_by': 'Status.All', 'contact_type': 'customer',
            'page': page, 'per_page': 200,
        })
        rows = response.get('contacts')
        context = response.get('page_context', {})
        if not isinstance(rows, list) or type(context.get('has_more_page')) is not bool:
            raise ValueError(f'Malformed customer page {page}; sync not committed')
        if 'page' in context and int(context['page']) != page:
            raise ValueError(f'Wrong response page for {page}')
        for row in rows:
            if row.get('contact_type') != 'customer':
                continue
            cid = str(row.get('contact_id') or '')
            stamp = row.get('last_modified_time')
            if not cid or not stamp or cid in records:
                raise ValueError(f'Missing identity/time or duplicate customer on page {page}')
            datetime.fromisoformat(stamp)
            records[cid] = row
        if not context['has_more_page']:
            break
        if not rows or page >= 10000:
            raise ValueError('Invalid pagination; sync not committed')
        page += 1
        time.sleep(request_delay)
    changed = 0
    with db:
        db.execute('UPDATE customer_snapshots SET present_in_cloud=0')
        for cid, row in records.items():
            stamp = row['last_modified_time']
            old = db.execute('SELECT * FROM customer_snapshots WHERE contact_id=?', (cid,)).fetchone()
            changed += int(old is None or old['last_modified_time'] != stamp)
            db.execute('''INSERT INTO customer_snapshots
                (contact_id,contact_name,status,last_modified_time,cloud_json)
                VALUES (?,?,?,?,?) ON CONFLICT(contact_id) DO UPDATE SET
                contact_name=excluded.contact_name,status=excluded.status,
                last_modified_time=excluded.last_modified_time,cloud_json=excluded.cloud_json,
                detail_json=CASE WHEN customer_snapshots.last_modified_time=excluded.last_modified_time
                    THEN customer_snapshots.detail_json ELSE NULL END,
                conflict=CASE WHEN customer_snapshots.local_json IS NOT NULL AND
                    customer_snapshots.edit_base_time!=excluded.last_modified_time THEN 1 ELSE 0 END,
                present_in_cloud=1''',
                (cid, row.get('contact_name', ''), row.get('status', ''), stamp, json.dumps(row)))
        db.execute('UPDATE customer_snapshots SET conflict=1 WHERE present_in_cloud=0 AND local_json IS NOT NULL')
        db.execute('INSERT INTO sync_runs(completed_at,pages,customers,changed) VALUES (?,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(), page, len(records), changed))
        materialize_customers(db)
    return {'pages': page, 'customers': len(records), 'changed': changed}


def stage_mobile_plan(db: sqlite3.Connection, plan_path: Path) -> dict[str, int]:
    """Atomically stage the previously reviewed phone moves from detail backups."""
    plan = json.loads(plan_path.read_text())
    if not plan['summary']['complete'] or plan['review'] or plan['failures']:
        raise ValueError('Preparation plan is incomplete or contains unresolved records')
    with db:
        capture_table_edits(db)
    staged = 0
    seen: set[str] = set()
    with db:
        for entry in plan['ready']:
            cid = entry['contact_id']
            if cid in seen:
                raise ValueError(f'Duplicate plan customer: {cid}')
            seen.add(cid)
            row = db.execute('SELECT * FROM customer_snapshots WHERE contact_id=?', (cid,)).fetchone()
            if row is None or not row['present_in_cloud'] or row['conflict']:
                raise ValueError(f'Missing or conflicting customer: {cid}')
            if row['last_modified_time'] != entry['last_modified_time']:
                raise ValueError(f'Cloud modification time changed for {cid}; review again')
            snapshot = Path(entry['before_file'])
            raw = json.loads(snapshot.read_text())
            detail = raw.get('contact', raw)
            cloud = json.loads(row['cloud_json'])
            phone = detail.get('phone', '')
            if (detail.get('contact_id') != cid or not phone or detail.get('mobile')
                or cloud.get('phone') != phone or cloud.get('mobile')
                or detail.get('last_modified_time') != row['last_modified_time']):
                raise ValueError(f'Phone/mobile baseline changed for {cid}')
            persons = [p for p in detail['contact_persons']
                       if p.get('contact_person_id') == entry['primary_contact_id']]
            if len(persons) != 1 or persons[0].get('phone') != phone or persons[0].get('mobile'):
                raise ValueError(f'Primary contact baseline changed for {cid}')
            before = json.dumps(detail)
            persons[0]['mobile'], persons[0]['phone'] = phone, ''
            detail['mobile'], detail['phone'] = phone, ''
            local = json.dumps(detail)
            if row['local_json'] is not None and json.loads(row['local_json']) != detail:
                raise ValueError(f'Existing local edits differ for {cid}')
            db.execute('''UPDATE customer_snapshots SET detail_json=?,edit_base_json=?,local_json=?,edit_base_time=?
                          WHERE contact_id=?''', (before, before, local, row['last_modified_time'], cid))
            staged += 1
        materialize_customers(db)
    return {'staged': staged, 'cloud_updates': 0}


def export_pending(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    """Export review data, deliberately not a Books API request body."""
    with db:
        capture_table_edits(db)
    rows = db.execute('SELECT * FROM customer_snapshots WHERE local_json IS NOT NULL ORDER BY contact_id').fetchall()
    result = [{'contact_id': r['contact_id'], 'base_modified_time': r['edit_base_time'],
               'conflict': bool(r['conflict']), 'present_in_cloud': bool(r['present_in_cloud']),
               'before': json.loads(r['edit_base_json']) if r['edit_base_json'] else None,
               'after': json.loads(r['local_json'])} for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'review_only': True, 'customers': result}, indent=2))
    return {'pending': len(rows), 'conflicts': sum(bool(r['conflict']) for r in rows)}


def stage_creator_beats_locally(db: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stage assigned Creator beats for active local customers, preserving manual beat edits."""
    from zoho.helpers.custom_fields import get_custom_field_value

    changes: list[dict[str, str]] = []
    preserved: list[dict[str, str]] = []
    missing: list[str] = []
    unassigned = inactive = unchanged = 0
    seen: set[str] = set()
    with db:
        if not db.in_transaction:
            db.execute('BEGIN')
        capture_table_edits(db)
        _expand_constants(db)
        columns = {r[1] for r in db.execute('PRAGMA table_info(customers)')}
        for key in ('cf_beat', 'cf_beat_formatted', 'cf_beat_unformatted', 'custom_fields', 'custom_field_hash'):
            if key not in columns:
                db.execute(f'ALTER TABLE customers ADD COLUMN "{key}"')
        for creator_row in rows:
            beat = str(creator_row.get('Beat.Beat_Name') or '').strip()
            if not beat:
                unassigned += 1
                continue
            cid = str(creator_row.get('Customer_Id') or '').strip()
            creator_id = str(creator_row.get('ID') or '').strip()
            if not cid.isdigit() or not creator_id.isdigit() or cid in seen:
                raise ValueError(f'Invalid or duplicate Creator customer link: {cid}')
            seen.add(cid)
            row = db.execute('SELECT * FROM customers WHERE contact_id=?', (cid,)).fetchone()
            if row is None:
                missing.append(cid)
                continue
            if row['status'] != 'active':
                inactive += 1
                continue
            current = str(row['cf_beat'] or '').strip()
            if current == beat:
                unchanged += 1
                continue
            snapshot = db.execute('SELECT * FROM customer_snapshots WHERE contact_id=?', (cid,)).fetchone()
            cloud_beat = str(get_custom_field_value(json.loads(snapshot['cloud_json']), 'cf_beat') or '').strip()
            item = {'contact_id': cid, 'creator_id': creator_id, 'customer': row['contact_name'],
                    'before': current, 'creator_beat': beat}
            if snapshot['conflict'] or current != cloud_beat:
                preserved.append(item)
                continue
            fields = json.loads(row['custom_fields'] or '[]')
            matches = [f for f in fields if f.get('api_name') == 'cf_beat']
            if len(matches) > 1:
                raise ValueError(f'Duplicate Beat custom fields for {cid}')
            if not matches:
                matches = [{'api_name': 'cf_beat'}]
                fields.extend(matches)
            matches[0]['value'] = matches[0]['value_formatted'] = beat
            field_hash = json.loads(row['custom_field_hash'] or '{}')
            for key in ('cf_beat', 'cf_beat_formatted', 'cf_beat_unformatted'):
                field_hash[key] = beat
            db.execute('''UPDATE customers SET cf_beat=?,cf_beat_formatted=?,cf_beat_unformatted=?,
                custom_fields=?,custom_field_hash=? WHERE contact_id=?''',
                (beat, beat, beat, json.dumps(fields), json.dumps(field_hash), cid))
            changes.append(item)
        capture_table_edits(db)
        materialize_customers(db)
    return {'scanned': len(rows), 'updated': len(changes), 'unchanged': unchanged,
            'unassigned': unassigned, 'inactive': inactive, 'missing': missing,
            'preserved_local_changes': preserved, 'changes': changes, 'cloud_updates': 0}
