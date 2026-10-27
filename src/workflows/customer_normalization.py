"""Four-table, local-only customer cleanup from preserved Analytics exports."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, TypedDict

from .analytics_catalog import AnalyticsCatalog
from .core.checkpoint import write_atomic_json


SOURCE_NAMES = {
    'customers': 'Customers (Zoho Books)',
    'addresses': 'Customer Addresses (Zoho Books)',
    'contact_persons': 'Customer Contact Persons (Zoho Books)',
}
FINANCIAL_FIELDS = {
    'Credit Limit', 'Payment Terms Label', 'Currency Code', 'Opening Balance',
    'Payments Due', 'Accounts Receivable', 'Bank Account Payment', 'PriceList ID',
    'Place Of Supply', 'Tax Exemption ID', 'GST Treatment', 'GSTIN', 'PAN Number',
    'Taxable', 'Tax ID', 'GST Registered', 'B2B ID',
}
BEAT_FIELDS = {
    'Beat', 'District', 'Branch', 'Jurisdiction', 'Transporter', 'Optical Division',
    'Customer Owner ID',
}
CATEGORY_FIELDS = {
    'Status', 'Customer Sub Type', 'Type', 'District', 'Branch', 'Jurisdiction',
    'Transporter', 'Optical Division', 'Beat', 'Status_1', 'GST Treatment',
    'Payment Terms Label', 'state',
}
FINANCIAL_AMOUNTS = {'Credit Limit', 'Opening Balance', 'Payments Due', 'Accounts Receivable'}
TABLES = ('Customers', 'Customer Addresses', 'Customer Financials', 'Customer Beat')


class Correction(TypedDict):
    table: str
    record_id: str
    column: str
    before: Any
    after: Any
    rule: str


class ReviewIssue(TypedDict):
    table: str
    record_id: str
    column: str
    value: Any
    reason: str


@dataclass(frozen=True)
class CustomerNormalizationResult:
    database: Path
    report: Path
    counts: dict[str, int]
    corrections: int
    review_issues: int
    last_metadata_sync: str


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def download_customer_normalization_sources(
    analytics: Any, catalog: AnalyticsCatalog, destination: Path, *, organization_id: str,
) -> Path:
    """Export all three sources using cached schema; never sync metadata or write ZA."""
    if destination.exists():
        raise FileExistsError(f'Source destination already exists: {destination}')
    with catalog.cached_store() as store:
        sources = {}
        for key, name in SOURCE_NAMES.items():
            matches = [v for v in store.find_views(name) if v['name'] == name]
            if len(matches) != 1:
                raise ValueError(f'Expected one cached Analytics table named {name!r}')
            view = matches[0]
            sources[key] = {'view_id': view['view_id'], 'name': name,
                            'columns': [c['name'] for c in store.get_columns(view['view_id'])]}
        synced_at = store.get_info('last_successful_sync_at')
    # Fetch every source before publishing a complete manifest.
    rows = {key: analytics.views.export_all(catalog.workspace_id, view['view_id'], max_attempts=60)
            for key, view in sources.items()}
    for key, view in sources.items():
        count = analytics.queries.execute(
            catalog.workspace_id, f'SELECT COUNT(*) AS source_count FROM {_quote(view["name"])}',
            max_attempts=60)
        if len(count) != 1 or str(count[0].get('source_count')) != str(len(rows[key])):
            raise ValueError(f'Analytics row count differs from exported rows: {view["name"]}; retry the export')
    destination.mkdir(parents=True)
    for key, records in rows.items():
        write_atomic_json(destination / f'{key}.json', records, ensure_ascii=False)
        sources[key]['rows'] = len(records)
    write_atomic_json(destination / 'manifest.json', {
        'organization_id': organization_id, 'workspace_id': catalog.workspace_id,
        'last_metadata_sync': synced_at, 'captured_at': datetime.now(timezone.utc).isoformat(),
        'views': sources, 'row_counts_verified': True,
    })
    return destination


def _identity(row: dict[str, Any], field: str, source: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
        raise ValueError(f'{source}: {field} must be an exact digit string, received {value!r}')
    return value


def _load_sources(source: Path, organization_id: str) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('organization_id') != organization_id:
        raise ValueError('Source exports belong to a different or unspecified Books organization')
    if not manifest.get('last_metadata_sync'):
        raise ValueError('Source manifest must include the last successful metadata sync')
    sources = {}
    for key, name in SOURCE_NAMES.items():
        rows = json.loads((source / f'{key}.json').read_text(encoding='utf-8'))
        description = manifest['views'][key]
        if description['name'] != name or not isinstance(rows, list) or len(rows) != description['rows']:
            raise ValueError(f'Incomplete or mismatched source export: {name}')
        columns = description['columns']
        required = {'Customer ID'}
        if key == 'addresses':
            required.add('Address ID')
        elif key == 'contact_persons':
            required.add('Contact Person ID')
        if not required.issubset(columns):
            raise ValueError(f'Source schema is missing identity columns: {name}')
        if len({c.casefold() for c in columns}) != len(columns):
            raise ValueError(f'Colliding source column names: {name}')
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError(f'Source row columns differ from cached schema: {name}')
        sources[key] = rows
    if not sources['customers']:
        raise ValueError('Customer export is empty; refusing to report an empty mirror as complete')
    ids: dict[str, set[str]] = {}
    for key, field in [('customers', 'Customer ID'), ('addresses', 'Address ID'),
                       ('contact_persons', 'Contact Person ID')]:
        ids[key] = set()
        for row in sources[key]:
            identity = _identity(row, field, key)
            if identity in ids[key]:
                raise ValueError(f'Duplicate {field} in {key}: {identity}')
            ids[key].add(identity)
            if key != 'customers' and _identity(row, 'Customer ID', key) not in ids['customers']:
                raise ValueError(f'Orphan {key} record: {identity}')
    return manifest, sources


def _normalized_value(column: str, value: Any) -> tuple[Any, str]:
    # IDs, dates, free-form notes and financial values retain their exact source values.
    if not isinstance(value, str) or column.endswith('ID') or column in FINANCIAL_AMOUNTS or column in {
        'Created Time', 'Last Modified Time', 'Created By', 'Modified By', 'Notes',
    }:
        return value, ''
    cleaned = value.strip()
    rule = 'trim_outer_whitespace'
    if column in CATEGORY_FIELDS:
        cleaned = ' '.join(cleaned.split())
        rule = 'normalize_label_whitespace'
    if column == 'Payment Terms Label':
        aliases = {'due on receipt': 'Due on Receipt', '30 days': 'Net 30'}
        cleaned = aliases.get(cleaned.casefold(), cleaned)
        rule = 'canonical_payment_terms'
    elif column in {'GSTIN', 'PAN Number', 'Currency Code', 'Place Of Supply'}:
        cleaned = cleaned.upper()
        rule = 'uppercase_identifier_or_code'
    elif column in {'Billing City', 'Shipping City'}:
        cleaned = ' '.join(cleaned.split()).upper()
        rule = 'canonical_city_case_and_spacing'
    elif column == 'Email' and cleaned.count('@') == 1:
        local, domain = cleaned.split('@')
        cleaned = local + '@' + domain.lower()
        rule = 'normalize_email_domain'
    elif column in {'Phone', 'Mobile Phone', 'Billing Phone', 'Shipping Phone'}:
        # Only a single conventional number: never guess country codes or split multiple numbers.
        candidate = re.sub(r'[ ()\-.]', '', cleaned)
        if re.fullmatch(r'\+?[0-9]{6,15}', candidate):
            cleaned = candidate
            rule = 'remove_single_phone_formatting'
    return cleaned, rule


def _normalize_record(
    row: dict[str, Any], table: str, identity: str,
    corrections: list[Correction], issues: list[ReviewIssue], *, prefix: str = '',
) -> dict[str, Any]:
    result = {}
    for column, before in row.items():
        after, rule = _normalized_value(column, before)
        result[column] = after
        if after != before:
            corrections.append({'table': table, 'record_id': identity, 'column': prefix + column,
                                'before': before, 'after': after, 'rule': rule})
        reason = ''
        if after and column in {'Phone', 'Mobile Phone', 'Billing Phone', 'Shipping Phone'}:
            if not isinstance(after, str) or not re.fullmatch(r'\+?[0-9]{6,15}', after):
                reason = 'Phone needs review: multiple numbers, extension, or invalid format'
        elif after and column == 'Email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', str(after)):
            reason = 'Email format needs review'
        elif after and column == 'GSTIN' and not re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]', str(after)):
            reason = 'GSTIN format needs review; no registration or checksum verification performed'
        elif after and column == 'PAN Number' and not re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', str(after)):
            reason = 'PAN format needs review'
        if reason:
            issues.append({'table': table, 'record_id': identity, 'column': prefix + column,
                           'value': after, 'reason': reason})
    return result


def _review_links(sources: dict[str, list[dict[str, Any]]], issues: list[ReviewIssue]) -> None:
    addresses = {r['Address ID']: r['Customer ID'] for r in sources['addresses']}
    beats: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in sources['customers']:
        cid = row['Customer ID']
        address_id = row.get('Default Address ID')
        if address_id and addresses.get(address_id) != cid:
            issues.append({'table': 'Customers', 'record_id': cid, 'column': 'Default Address ID',
                           'value': address_id, 'reason': 'Default address missing or belongs to another customer'})
        if str(row.get('GST Treatment', '')).startswith('Registered Business') and not row.get('GSTIN'):
            issues.append({'table': 'Customer Financials', 'record_id': cid, 'column': 'GSTIN',
                           'value': row.get('GSTIN'), 'reason': 'Registered-business customer has no GSTIN'})
        gst, pan = row.get('GSTIN', ''), row.get('PAN Number', '')
        if gst and pan and len(gst) == 15 and gst[2:12].upper() != pan.upper():
            issues.append({'table': 'Customer Financials', 'record_id': cid, 'column': 'PAN Number',
                           'value': pan, 'reason': 'PAN differs from PAN portion of GSTIN'})
        if row.get('Beat'):
            beats[(row.get('Branch', ''), row.get('Jurisdiction', ''))].add(row['Beat'])
    for (branch, jurisdiction), names in beats.items():
        ordered = sorted(names)
        for index, name in enumerate(ordered):
            for other in ordered[index + 1:]:
                if SequenceMatcher(None, name.casefold(), other.casefold()).ratio() >= .90:
                    issues.append({'table': 'Customer Beat', 'record_id': '', 'column': 'Beat',
                                   'value': [name, other],
                                   'reason': f'Similar beat names in {branch}/{jurisdiction}; explicit mapping required'})


def _create_table(db: sqlite3.Connection, table: str, columns: list[str], primary: str) -> None:
    if len({c.casefold() for c in columns}) != len(columns):
        raise ValueError(f'Colliding columns in {table}')
    definitions = []
    for column in columns:
        constraint = ' TEXT PRIMARY KEY NOT NULL' if column == primary else ''
        if column == 'Customer ID' and table != 'Customers':
            constraint += ' NOT NULL REFERENCES "Customers"("Customer ID")'
        definitions.append(_quote(column) + constraint)
    db.execute(f'CREATE TABLE {_quote(table)} ({",".join(definitions)})')


def _insert(db: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ','.join(_quote(c) for c in row)
    values = [_json(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    db.execute(f'INSERT INTO {_quote(table)} ({columns}) VALUES ({",".join("?" for _ in row)})', values)


def build_normalized_customers(
    source: Path, destination: Path, *, organization_id: str,
) -> CustomerNormalizationResult:
    """Create four related tables and audited local fixes; refuse to overwrite edited stores."""
    if destination.exists():
        raise FileExistsError(f'Database exists: {destination}; choose a new --db to preserve local edits')
    manifest, sources = _load_sources(source, organization_id)
    customer_columns = manifest['views']['customers']['columns']
    groups = {
        'Customers': [c for c in customer_columns if c not in FINANCIAL_FIELDS | BEAT_FIELDS],
        'Customer Financials': ['Customer ID'] + [c for c in customer_columns if c in FINANCIAL_FIELDS],
        'Customer Beat': ['Customer ID'] + [c for c in customer_columns if c in BEAT_FIELDS],
    }
    groups['Customers'] += ['Contact Persons', '_source_json', '_source_contact_persons_json']
    groups['Customer Addresses'] = manifest['views']['addresses']['columns'] + ['_source_json']
    persons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for person in sources['contact_persons']:
        persons[person['Customer ID']].append(person)
    corrections: list[Correction] = []
    issues: list[ReviewIssue] = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects previously staged values even when two imports race.
    destination.open('xb').close()
    db = sqlite3.connect(destination)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            for table in TABLES:
                _create_table(db, table, groups[table], 'Address ID' if table == 'Customer Addresses' else 'Customer ID')
            for original in sources['customers']:
                cid = original['Customer ID']
                for table in ('Customers', 'Customer Financials', 'Customer Beat'):
                    part = {c: original[c] for c in groups[table] if c in original}
                    normalized = _normalize_record(part, table, cid, corrections, issues)
                    if table == 'Customers':
                        normalized['Contact Persons'] = [
                            _normalize_record(person, table, cid, corrections, issues,
                                              prefix=f'Contact Persons[{person["Contact Person ID"]}].')
                            for person in persons[cid]]
                        normalized['_source_json'] = original
                        normalized['_source_contact_persons_json'] = persons[cid]
                    _insert(db, table, normalized)
            for original in sources['addresses']:
                normalized = _normalize_record(original, 'Customer Addresses', original['Address ID'], corrections, issues)
                normalized['_source_json'] = original
                _insert(db, 'Customer Addresses', normalized)
            _review_links(sources, issues)
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign-key validation failed')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
            counts = {table: db.execute(f'SELECT count(*) FROM {_quote(table)}').fetchone()[0] for table in TABLES}
            expected = {t: len(sources['addresses'] if t == 'Customer Addresses' else sources['customers']) for t in TABLES}
            if counts != expected:
                raise ValueError(f'Row count mismatch: {counts} != {expected}')
            # Every original source row must be reconstructable, including secondary contacts.
            saved_customers = [json.loads(r[0]) for r in db.execute('SELECT _source_json FROM "Customers" ORDER BY "Customer ID"')]
            if saved_customers != sorted(sources['customers'], key=lambda r: r['Customer ID']):
                raise ValueError('Customer source preservation check failed')
            saved_addresses = [json.loads(r[0]) for r in db.execute('SELECT _source_json FROM "Customer Addresses" ORDER BY "Address ID"')]
            if saved_addresses != sorted(sources['addresses'], key=lambda r: r['Address ID']):
                raise ValueError('Address source preservation check failed')
            saved_persons = [p for r in db.execute('SELECT _source_contact_persons_json FROM "Customers"') for p in json.loads(r[0])]
            if sorted(saved_persons, key=lambda r: r['Contact Person ID']) != sorted(sources['contact_persons'], key=lambda r: r['Contact Person ID']):
                raise ValueError('Contact-person source preservation check failed')
        schema = ';\n'.join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY rowid")) + ';\n'
    except BaseException:
        db.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        db.close()
    report = destination.with_suffix('.report.json')
    payload = {
        'database': str(destination), 'organization_id': organization_id, 'source': str(source),
        'last_metadata_sync': manifest['last_metadata_sync'], 'source_captured_at': manifest['captured_at'],
        'counts': counts, 'contact_persons_preserved': len(sources['contact_persons']),
        'columns': groups, 'corrections': corrections, 'review_issues': issues, 'cloud_updates': 0,
        'verification': 'SQLite integrity, foreign keys, counts and all original source records passed',
    }
    write_atomic_json(report, payload, ensure_ascii=False)
    destination.with_suffix('.schema.sql').write_text(schema, encoding='utf-8')
    rules = Counter(c['rule'] for c in corrections)
    reasons = Counter(i['reason'] for i in issues)
    lines = ['# Customer normalization', '', f'Last successful metadata sync (UTC): {manifest["last_metadata_sync"]}',
             '', f'Source capture (UTC): {manifest["captured_at"]}', '',
             '| Table | Rows |', '|---|---:|', *[f'| {t} | {n} |' for t, n in counts.items()], '',
             f'Contact persons retained in Customers: {len(sources["contact_persons"])}.', '',
             f'Applied local corrections: {len(corrections)}. Review issues: {len(issues)}. Cloud updates: 0.', '',
             '## Applied corrections', '', *[f'- {rule}: {n}' for rule, n in rules.items()], '',
             '## Review required', '', *[f'- {reason}: {n}' for reason, n in reasons.items()], '',
             'Original rows are preserved in source JSON columns. Detailed before/after values are in the JSON report.',
             'Financial amounts and identifiers retain source representation. No geographic or fuzzy spelling merges are applied.',
             'Contact persons are retained as an editable JSON array to honor the four-table layout.',
             'This database is a local Analytics snapshot; connector data can lag Books. Cloud writes require a separate reviewed workflow.']
    destination.with_suffix('.report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return CustomerNormalizationResult(destination, report, counts, len(corrections), len(issues), manifest['last_metadata_sync'])
