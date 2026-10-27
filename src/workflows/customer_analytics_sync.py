"""Repeatable Analytics-to-SQLite synchronization with local cleanup reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, TypedDict

from .analytics_catalog import AnalyticsCatalog
from .core.checkpoint import write_atomic_json
from .customer_normalization import (
    TABLES, _json, _load_sources, _normalize_record, _quote,
    build_normalized_customers, download_customer_normalization_sources,
)


TECHNICAL = {'_source_json', '_source_contact_persons_json', '_baseline_json',
             '_sync_info_json', '_sync_conflicts_json', '_present_in_analytics'}
SYNC_COLUMNS = ('_baseline_json', '_sync_conflicts_json', '_present_in_analytics')
_MISSING = object()


class CustomerSyncConflict(TypedDict):
    table: str
    record_id: str
    column: str
    reason: str
    baseline: Any
    local: Any
    analytics: Any
    baseline_present: bool
    local_present: bool
    analytics_present: bool


@dataclass(frozen=True)
class CustomerAnalyticsSyncResult:
    database: Path
    report: Path
    source: Path
    backup: Path | None
    counts: dict[str, int]
    added: dict[str, int]
    updated: dict[str, int]
    missing_from_analytics: dict[str, int]
    preserved_local_fields: int
    conflicts: int
    last_metadata_sync: str


def _primary(table: str) -> str:
    return 'Address ID' if table == 'Customer Addresses' else 'Customer ID'


def _read_tables(db: sqlite3.Connection) -> dict[str, dict[str, dict[str, Any]]]:
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != set(TABLES):
        raise ValueError('Sync requires the four-table normalization database, not the legacy Books store')
    return {table: {row[_primary(table)]: dict(row)
                    for row in db.execute(f'SELECT * FROM {_quote(table)}')}
            for table in TABLES}


def _business(row: dict[str, Any]) -> dict[str, Any]:
    result = {k: v for k, v in row.items() if k not in TECHNICAL}
    if 'Contact Persons' in result:
        try:
            persons = json.loads(result['Contact Persons'])
        except (TypeError, ValueError) as exc:
            raise ValueError('Contact Persons must remain a JSON array') from exc
        _persons_by_id(persons)
        result['Contact Persons'] = persons
    return result


def _persons_by_id(persons: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(persons, list):
        raise ValueError('Contact Persons must remain a JSON array')
    result = {}
    for person in persons:
        cid = person.get('Contact Person ID') if isinstance(person, dict) else None
        if not isinstance(cid, str) or not cid.isascii() or not cid.isdigit() or cid in result:
            raise ValueError('Contact Persons contain missing, invalid, or duplicate IDs')
        result[cid] = person
    return result


def _same(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return _json(left) == _json(right)


def _conflict(table: str, rid: str, column: str, reason: str,
              base: Any, local: Any, incoming: Any) -> CustomerSyncConflict:
    return {'table': table, 'record_id': rid, 'column': column, 'reason': reason,
            'baseline': None if base is _MISSING else base,
            'local': None if local is _MISSING else local,
            'analytics': None if incoming is _MISSING else incoming,
            'baseline_present': base is not _MISSING, 'local_present': local is not _MISSING,
            'analytics_present': incoming is not _MISSING}


def _merge_fields(
    table: str, rid: str, base: dict[str, Any], local: dict[str, Any], incoming: dict[str, Any],
    conflicts: list[CustomerSyncConflict], *, prefix: str = '',
) -> tuple[dict[str, Any], dict[str, Any], int]:
    merged, baseline, preserved = {}, {}, 0
    for key in dict.fromkeys([*base, *local, *incoming]):
        old, ours, theirs = base.get(key, _MISSING), local.get(key, _MISSING), incoming.get(key, _MISSING)
        if key == 'Contact Persons' and prefix == '':
            value, checkpoint, kept = _merge_persons(table, rid, old, ours, theirs, conflicts)
            merged[key], baseline[key] = value, checkpoint
            preserved += kept
            continue
        if _same(ours, old):
            value, checkpoint = theirs, theirs
        elif _same(ours, theirs):
            value, checkpoint = theirs, theirs
        elif _same(theirs, old):
            value, checkpoint = ours, theirs
            preserved += 1
        else:
            value, checkpoint = ours, old
            preserved += 1
            conflicts.append(_conflict(table, rid, prefix + key,
                                       'Local and Analytics values both changed', old, ours, theirs))
        if value is not _MISSING:
            merged[key] = value
        if checkpoint is not _MISSING:
            baseline[key] = checkpoint
    return merged, baseline, preserved


def _merge_persons(table: str, rid: str, base: Any, local: Any, incoming: Any,
                   conflicts: list[CustomerSyncConflict]) -> tuple[list[Any], list[Any], int]:
    old = _persons_by_id(base)
    ours = _persons_by_id(local)
    theirs = _persons_by_id(incoming)
    if set(old) != set(ours):
        raise ValueError(f'{rid}: contact-person IDs/rows were edited; restore identities before syncing')
    merged, baseline, preserved = [], [], 0
    # Export order is not a contact-person attribute; retain local order and append new IDs.
    for pid in dict.fromkeys([*ours, *theirs]):
        if pid not in old:
            value, checkpoint = theirs[pid], theirs[pid]
        elif pid not in theirs:
            value, checkpoint = ours[pid], old[pid]
            conflicts.append(_conflict(table, rid, f'Contact Persons[{pid}]',
                                       'Contact person missing from Analytics; retained locally',
                                       old[pid], ours[pid], _MISSING))
        else:
            for candidate in (ours[pid], theirs[pid]):
                if candidate.get('Customer ID') != old[pid].get('Customer ID'):
                    raise ValueError(f'{rid}: contact-person ownership changed for {pid}; review before syncing')
            value, checkpoint, kept = _merge_fields(table, rid, old[pid], ours[pid], theirs[pid], conflicts,
                                                     prefix=f'Contact Persons[{pid}].')
            preserved += kept
        merged.append(value)
        baseline.append(checkpoint)
    return merged, baseline, preserved


def _initial_baseline(table: str, row: dict[str, Any], customers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    original = json.loads(row['_source_json'] if table == 'Customer Addresses'
                          else customers[row['Customer ID']]['_source_json'])
    fields = {key: original[key] for key in _business(row) if key in original}
    baseline = _normalize_record(fields, table, row[_primary(table)], [], [])
    if table == 'Customers':
        baseline['Contact Persons'] = [_normalize_record(p, table, row['Customer ID'], [], [])
                                      for p in json.loads(row['_source_contact_persons_json'])]
    return baseline


def _validate_target(
    rows: dict[str, dict[str, dict[str, Any]]], destination: Path,
    organization_id: str, workspace_id: str,
) -> None:
    if not rows['Customers']:
        raise ValueError('Existing customer store is empty; refusing to infer its ownership')
    infos = {r.get('_sync_info_json') for r in rows['Customers'].values()}
    if infos == {None}:
        # Upgrade the previously created one-off snapshot using its preserved provenance.
        report_path = destination.with_suffix('.report.json')
        if not report_path.is_file():
            raise ValueError('Initial snapshot report is required to verify database ownership')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        manifest, _ = _load_sources(Path(report['source']), organization_id)
        if manifest.get('workspace_id') != workspace_id or report.get('organization_id') != organization_id:
            raise ValueError('Database belongs to another organization or Analytics workspace')
        counts = report['counts']
    else:
        if None in infos or len(infos) != 1:
            raise ValueError('Sync metadata was changed or customer rows were inserted directly')
        info = json.loads(next(iter(infos)))
        if info['organization_id'] != organization_id or info['workspace_id'] != workspace_id:
            raise ValueError('Database belongs to another organization or Analytics workspace')
        counts = info['counts']
    if counts != {table: len(records) for table, records in rows.items()}:
        raise ValueError('Rows were inserted/deleted directly; restore them before syncing')
    for table, records in rows.items():
        for rid, row in records.items():
            if row.get('_baseline_json'):
                baseline = json.loads(row['_baseline_json'])
            else:
                baseline = _initial_baseline(table, row, rows['Customers'])
            for key in {_primary(table), 'Customer ID'}:
                if not _same(row.get(key), baseline.get(key)):
                    raise ValueError(f'{table}/{rid}: identity or ownership was edited; restore it before syncing')


def _store_row(db: sqlite3.Connection, table: str, row: dict[str, Any], *, exists: bool) -> None:
    values = {k: _json(v) if isinstance(v, (list, dict)) else v for k, v in row.items()}
    if exists:
        assignments = ','.join(f'{_quote(k)}=?' for k in values)
        db.execute(f'UPDATE {_quote(table)} SET {assignments} WHERE {_quote(_primary(table))}=?',
                   [*values.values(), row[_primary(table)]])
    else:
        db.execute(f'INSERT INTO {_quote(table)} ({",".join(_quote(k) for k in values)}) '
                   f'VALUES ({",".join("?" for _ in values)})', list(values.values()))


def _verify_person_ownership(old: dict[str, dict[str, dict[str, Any]]], incoming: dict[str, dict[str, dict[str, Any]]]) -> None:
    owners = {}
    for cid, row in old['Customers'].items():
        base = (json.loads(row['_baseline_json']) if row.get('_baseline_json')
                else _initial_baseline('Customers', row, old['Customers']))
        for person in base['Contact Persons']:
            pid = person['Contact Person ID']
            if pid in owners:
                raise ValueError(f'Duplicate tracked contact-person identity: {pid}')
            owners[pid] = cid
    for cid, row in incoming['Customers'].items():
        for person in _business(row)['Contact Persons']:
            pid = person['Contact Person ID']
            if pid in owners and owners[pid] != cid:
                raise ValueError(f'Analytics contact-person ownership changed for {pid}; review before syncing')


def sync_analytics_customers(
    analytics: Any, catalog: AnalyticsCatalog, destination: Path, *, organization_id: str,
    source: Path | None = None,
) -> CustomerAnalyticsSyncResult:
    """Sync all four tables atomically; retain edits, missing rows and unresolved conflicts."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run = destination.parent / 'sync_runs' / stamp
    run.mkdir(parents=True)
    if source is None:
        source = download_customer_normalization_sources(analytics, catalog, run / 'source',
                                                        organization_id=organization_id)
    manifest, _ = _load_sources(source, organization_id)
    if manifest.get('workspace_id') != catalog.workspace_id:
        raise ValueError('Source exports belong to another Analytics workspace')
    if any(set(v['columns']) & TECHNICAL for v in manifest['views'].values()):
        raise ValueError('Analytics column names collide with reserved sync metadata')
    staged = build_normalized_customers(source, run / 'incoming.sqlite3', organization_id=organization_id)
    incoming_db = sqlite3.connect(staged.database)
    incoming_db.row_factory = sqlite3.Row
    try:
        incoming = _read_tables(incoming_db)
    finally:
        incoming_db.close()
    created = not destination.exists()
    if created:
        destination.open('xb').close()
    db = sqlite3.connect(destination, timeout=30)
    db.row_factory = sqlite3.Row
    backup = None
    conflicts: list[CustomerSyncConflict] = []
    preserved = 0
    added, updated, missing = ({t: 0 for t in TABLES} for _ in range(3))
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        if created:
            for table in TABLES:
                sql = sqlite3.connect(staged.database)
                try:
                    statement = sql.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
                finally:
                    sql.close()
                db.execute(statement)
            old = {t: {} for t in TABLES}
        else:
            old = _read_tables(db)
            _validate_target(old, destination, organization_id, catalog.workspace_id)
            _verify_person_ownership(old, incoming)
            backup = run / 'before_sync.sqlite3'
            # A separate reader backs up the committed state while BEGIN IMMEDIATE blocks other writers.
            reader = sqlite3.connect(destination.resolve().as_uri() + '?mode=ro', uri=True)
            checkpoint = sqlite3.connect(backup)
            try:
                reader.backup(checkpoint)
            finally:
                checkpoint.close()
                reader.close()
        for table in TABLES:
            existing = {r[1] for r in db.execute(f'PRAGMA table_info({_quote(table)})')}
            columns = set(next(iter(incoming[table].values()))) if incoming[table] else set(
                manifest['views']['addresses']['columns'] + ['_source_json'])
            columns.update(SYNC_COLUMNS)
            if table == 'Customers':
                columns.add('_sync_info_json')
            for column in sorted(columns - existing):
                db.execute(f'ALTER TABLE {_quote(table)} ADD COLUMN {_quote(column)}')
            for rid, incoming_row in incoming[table].items():
                theirs = _business(incoming_row)
                row_conflicts: list[CustomerSyncConflict] = []
                if rid in old[table]:
                    current = old[table][rid]
                    ours = _business(current)
                    base = (json.loads(current['_baseline_json']) if current.get('_baseline_json')
                            else _initial_baseline(table, current, old['Customers']))
                    if set(base) - set(theirs):
                        raise ValueError(f'{table}: Analytics removed columns; review schema before syncing')
                    if current['Customer ID'] != incoming_row['Customer ID']:
                        raise ValueError(f'{table}/{rid}: Analytics ownership changed; review before syncing')
                    merged, baseline, kept = _merge_fields(table, rid, base, ours, theirs, row_conflicts)
                    preserved += kept
                    updated[table] += int(not _same(merged, ours))
                else:
                    merged, baseline = theirs, theirs
                    added[table] += 1
                values = {**merged, **{k: v for k, v in incoming_row.items() if k in TECHNICAL},
                          '_baseline_json': baseline, '_sync_conflicts_json': row_conflicts,
                          '_present_in_analytics': 1}
                _store_row(db, table, values, exists=rid in old[table])
                conflicts.extend(row_conflicts)
            for rid, current in old[table].items():
                if rid in incoming[table]:
                    continue
                missing[table] += 1
                base = (json.loads(current['_baseline_json']) if current.get('_baseline_json')
                        else _initial_baseline(table, current, old['Customers']))
                ours = _business(current)
                issue = _conflict(table, rid, '', 'Record missing from Analytics; retained locally', base, ours, _MISSING)
                _store_row(db, table, {**current, '_baseline_json': base, '_present_in_analytics': 0,
                                       '_sync_conflicts_json': [issue]}, exists=True)
                conflicts.append(issue)
        counts = {t: db.execute(f'SELECT count(*) FROM {_quote(t)}').fetchone()[0] for t in TABLES}
        info = {'organization_id': organization_id, 'workspace_id': catalog.workspace_id,
                'counts': counts, 'last_successful_data_sync_at': datetime.now(timezone.utc).isoformat(),
                'last_metadata_sync': manifest['last_metadata_sync'], 'source_captured_at': manifest['captured_at'],
                'source': str(source.resolve()), 'report': str((run / 'sync_report.json').resolve())}
        db.execute('UPDATE "Customers" SET _sync_info_json=?', (_json(info),))
        if db.execute('PRAGMA foreign_key_check').fetchall() or db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity/foreign-key verification failed; sync rolled back')
        schema = ';\n'.join(r[0] for r in db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY rowid")) + ';\n'
        db.commit()
    except BaseException:
        db.rollback()
        db.close()
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        db.close()
    report = run / 'sync_report.json'
    payload = {**info, 'database': str(destination), 'backup': str(backup) if backup else None,
               'source_counts': {t: len(incoming[t]) for t in TABLES}, 'added': added, 'updated': updated,
               'missing_from_analytics': missing, 'preserved_local_fields': preserved,
               'conflicts': conflicts, 'normalization_report': str(staged.report), 'cloud_updates': 0}
    write_atomic_json(report, payload, ensure_ascii=False)
    lines = ['# Customer Analytics sync', '',
             f'Last successful data sync (UTC): {info["last_successful_data_sync_at"]}', '',
             f'Last successful metadata sync (UTC): {manifest["last_metadata_sync"]}', '',
             '| Table | Stored | Source | Added | Updated | Missing, retained |', '|---|---:|---:|---:|---:|---:|',
             *[f'| {t} | {counts[t]} | {len(incoming[t])} | {added[t]} | {updated[t]} | {missing[t]} |' for t in TABLES], '',
             f'Local fields preserved: {preserved}. Conflicts requiring review: {len(conflicts)}. Cloud updates: 0.', '',
             'Detailed conflicts and source/report/backup paths are in sync_report.json.',
             'Normalizations and source-format review issues are in incoming.report.json/incoming.report.md.',
             'Missing records are retained and flagged. Analytics connector data may lag Books.']
    report.with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_atomic_json(destination.with_suffix('.sync.json'), payload, ensure_ascii=False)
    destination.with_suffix('.schema.sql').write_text(schema, encoding='utf-8')
    return CustomerAnalyticsSyncResult(destination, report, source, backup, counts, added, updated, missing,
                                       preserved, len(conflicts), manifest['last_metadata_sync'])
