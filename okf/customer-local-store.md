---
type: workflow
description: Local Books customer SQLite mirror, modification-time reconciliation and reviewed local edits.
---

# Local customer store

`apps/customer_local_store.py` owns the local Books customer cleanup workflow;
`workflows.customer_local_store` contains persistence and reconciliation. It never
writes to Books. The default database is `output/customer_cleanup/customers.sqlite3`.
Organization identity is pinned in database metadata; another organization is rejected.

```sh
.venv/bin/python apps/customer_local_store.py migrate
.venv/bin/python apps/customer_local_store.py compact
.venv/bin/python apps/customer_local_store.py sync
.venv/bin/python apps/customer_local_store.py stage-mobile --plan output/customer_cleanup/mobile_empty_preparation/plan.json
.venv/bin/python apps/customer_local_store.py export
.venv/bin/python apps/customer_local_store.py csv
.venv/bin/python apps/customer_local_store.py json --contact-id BOOKS_CONTACT_ID
```

Sync fetches active and inactive customers using `per_page=200`. It scans all list
pages and compares each `last_modified_time` locally. A server-side modified-time
filter is not assumed. This is incremental reconciliation, not a delta API download.
Vendor responses are excluded; duplicate IDs, missing modification times and malformed
pagination fail the scan without committing partial data. Only completed scans enter
`sync_runs`. Missing customers are marked absent, never deleted automatically.
`customers` is the editable table: every observed top-level JSON key retains its exact
name as a column in `customers` or its singleton `customer_constants` table. Values combine list data, valid cached details and staged local edits.
Nested objects/arrays remain valid JSON in their same-named columns (for example,
`billing_address` and `contact_persons`); they are not flattened into ambiguous names.
Columns have no SQLite type affinity so string identifiers and mixed string/number
fields retain their values. `customer_record_shapes` records per-customer key presence
and value types, allowing `workflows.customer_table.customer_json` to reconstruct
booleans, nulls, absent keys, objects and arrays without loss. New non-null column values
are included in reconstructed JSON. Keep nested JSON structurally valid.

`customer_snapshots` owns cloud snapshots, staged checkpoints and sync metadata;
those internal fields are not customer API columns. The initial migration backs up the
legacy database to `output/customer_cleanup/backups/` before renaming its table.
Migration requires no network requests and is idempotent.

List responses omit addresses/contact-person details; only previously downloaded
detail records supply those columns. This remains an incomplete detail mirror.
A changed cloud timestamp invalidates cached details.

Edit customer fields directly in `customers`. Sync and pending-export operations
first checkpoint changed rows into `customer_snapshots.local_json`, preserving
`edit_base_json` and `edit_base_time`. Do not edit `contact_id`, `contact_type` or
`last_modified_time`, or insert/delete customer rows directly; checkpointing rejects
these changes. Contact-person fields are separate nested values: edits to top-level
phone/mobile do not automatically change their contact-person counterparts.

Local checkpoints retain immutable `edit_base_json` and `edit_base_time`.
A later cloud modification or disappearance sets `conflict`, retaining local edits
and their baseline. `customer_review` is a SQL view exposing cloud and local phone/mobile
values. The reviewed mobile-plan importer validates every baseline, phone/mobile value
and primary-person identity, and stages the entire batch atomically. Reapplying the same
plan is idempotent; differing existing edits are rejected. It preserves phone formatting
when copying to mobile, clears phone, and adjusts the corresponding primary person.
Snapshot paths in this trusted local preparation plan identify the original detail files.

Export produces `output/customer_cleanup/pending_changes.json` containing before/after
records, modification baselines and conflict flags. This is review data, not an API
payload. A future push must reject conflicts and absent customers, reread cloud details,
check stale baselines, construct validated minimal Books payloads, preserve other contact
persons, checkpoint writes, throttle requests and verify saved records. No push command
is provided yet. Address cleanup has not been staged by this workflow.

The `csv` action writes all customer columns to `customers_table.csv`; it does not
import edited CSV files. The `json` action prints the current reconstructed customer
record. Full reconstructed records contain response-only fields; a future cloud push
must select valid writable fields rather than sending the whole record unchanged.

## Related custom modules

`apps/download_books_custom_modules.py` downloads Books Sales Person (`cm_user`)
and Beat (`cm_beat`) into `output/books_custom_modules/modules.sqlite3`, in tables
`sales_persons` and `beats`. This database is separate from the customer database.
The command uses 200-row pages and `Status.All`; no Books writes are performed.
API module names were confirmed using Books `GET /settings/modules`.

```sh
.venv/bin/python apps/download_books_custom_modules.py
```

Columns retain exact JSON field names. Nested values remain JSON in their columns;
`workflows.books_custom_module_store.module_record_json` reconstructs the record
using the raw snapshot's types/key presence. IDs and modification times are retained.
`module_snapshots` preserves original records and `metadata` pins organization and
successful sync times. Both modules must finish fetching before local replacement.
A refresh refuses to overwrite direct table edits or records whose IDs were changed;
it does not yet merge edited module records or push them to Books. The customer
store's incremental conflict reconciliation is not applied to these module tables.
Sales-person and beat CSV files are review exports, not automatic import inputs.
The API contract is documented in [Books custom modules](https://www.zoho.com/books/api/v3/custom-modules/).

`stage_new_beat(database, name=...)` adds a local beat and a `module_local_creates`
entry. The `module_record_id` uses a `local:` UUID rather than pretending to be a
Books ID. The next zero-padded `cf_beat_id`/`record_name` is a local proposal and
must be checked against cloud numbering before a future create. Cloud-managed
status and timestamps remain unset. Refresh refuses pending creations. JSON
reconstruction supports these local records; creation in Books is not implemented.

## Creator beat assignments into SQLite

`stage_creator_beats_locally(db, rows)` consumes Creator customer report records
(`Customer_Id`, `ID`, `Beat.Beat_Name`) and changes only the local `customers` table.
It matches exact Books customer IDs, skips inactive customers and blank assignments,
reports missing local customers, and rejects duplicate/invalid links atomically.
It preserves local beat overrides and conflicted records, reporting the Creator proposal
for review. It copies Creator beat names exactly as text without creating or renaming
Books custom-module beats. Module beat names need not match this contact text field.

Updates keep `cf_beat`, formatted/unformatted counterparts, `custom_fields` and
`custom_field_hash` consistent. Other staged fields are retained. The entire batch
is checkpointed through the existing local edit workflow; no Books or Creator writes
are performed. The live report snapshot and local assignment result belong under the
customer output directory; refresh customer CSV/pending exports after applying.

## Shared customer constants

The `compact` action moves every uniform column except the row identity `contact_id`
from `customers` into `customer_constants`, a table with exactly one row and the
original field names. Uniformity includes NULL and uses SQLite value and storage type;
integer and real values are not conflated. The singleton insert trigger prevents
additional rows, and reconstruction rejects a missing singleton row. Per-record shape
metadata preserves missing JSON keys versus explicit NULL values.

`customers_full` joins the variable and shared columns; the CSV action exports this
full view. `customer_json` merges both tables before rebuilding JSON, and pending-edit
checkpointing detects edits to shared values. A shared-value edit affects all customers;
identity fields still cannot be changed. JSON reconstruction and full export keep
original field names. SQL queries that previously selected a moved field should use
`customers_full` (for example `contact_type` or `currency_code`).

After compaction is enabled in metadata, subsequent materialization temporarily restores
the full schema, rebuilds from cloud/local checkpoints and splits constants again in
the same transaction. A formerly shared field that varies in new data automatically
returns to `customers`. The initial live compaction retains a SQLite backup in `backups/`.
