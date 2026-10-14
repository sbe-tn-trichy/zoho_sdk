---
type: Concept
title: Zoho Analytics Metadata Snapshots
description: Read-only, resumable workspace metadata collection and relationship-map generation.
tags: [analytics, metadata, relationships, rate-limits, snapshots]
sources:
  - id: metadata-resource
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/zoho/analytics/metadata.py
    title: Analytics metadata resource
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# Metadata Snapshot API

`ZohoAnalyticsAPI.metadata` provides read-only methods for workspace details,
folders, data sources, paginated views, view details, table columns, and column
dependents. `download_workspace()` combines these endpoints into a versioned,
resumable snapshot.

The snapshot uses a single `metadata.sqlite` database. Workspace, folder,
data-source, view, column, and relationship fields used for lookup are
normalized and indexed. Uncommon raw Zoho fields are retained as compressed
JSON blobs, avoiding duplicate catalog and per-object files while preserving
the complete API response. Integer entity keys keep the relationship indexes
compact. A generated `summary.md` provides a human-readable inventory.

`WorkspaceMetadataStore` supports indexed view-name/type searches, column
lookup by view ID, and incoming/outgoing relationship traversal without loading
the complete snapshot into memory.

# Incremental Synchronization

Schema version 5 adds `query_tables` with exact saved SQL, definition hashes,
source modification markers, synchronization times and compressed raw responses.
Versions 3 and 4 migrate in place; existing version 3 stores need a workspace ID.
Older stores are marked incomplete until refreshed. Full and incremental sync
fetch missing or changed query definitions through the query-table details endpoint.
Failed definitions remain retryable and prevent successful synchronization.

`workflow_view_usage` records explicit workflow/view/operation/source mappings.
Remote synchronization preserves these records, including deleted view IDs so
missing consumers remain visible. `views_with_workflows.used_by_workflows` exposes
an aggregated column. `workflow_impact()` follows incoming `view_uses_view` edges
transitively, with cycle protection, to find indirect consumers.

`sync_workspace()` fetches the lightweight view inventory in pages of 200 and
compares each view's general `lastModifiedTime` with its successfully synchronized
marker in SQLite. It fetches details and table metadata only for new or changed
views, removes deleted views, and reconstructs relationships from the local
snapshot. Separate discovered and synchronized markers ensure a failed request
is retried on the next run. SHA-256 content hashes prevent unnecessary row and
column rewrites when the remote timestamp changes without a metadata change.
Data updates can advance this general timestamp even when design is unchanged;
it is not a dedicated design-change marker. Synchronization is an explicit manual
operation rather than a prerequisite for every analysis.

# Authentication

Metadata access requires `ZohoAnalytics.metadata.read`. The convenience factory
`ZohoAnalyticsAPI.from_token_provider()` retrieves `zoho_analytics_conn` from an
HTTP token broker at `http://localhost:3000/server/new/tokens` by default. The
URL remains overridable, and `zoho_analytics_conn` falls back to the broker's
`analytics` token key. Tokens and authorization headers are never written to
snapshot files or progress output.

# Rate Limits and Resume

Workspace downloads default to 50 metadata requests per minute. Error `6045`
and HTTP 429 responses trigger visible, immediately flushed console warnings,
bounded exponential backoff, and a recovery message when requests resume. The
collector records completion in `metadata.sqlite` after every completed object.
If retries are exhausted, it reports that the download is paused and the next
run can resume.

# Snapshot Files

`workflows.analytics_catalog.AnalyticsCatalog` is the supported entry point for
design planning and metadata analysis. Its `analyze()` and `cached_store()` use
existing SQLite metadata without remote requests. A missing catalog or one without
a successful sync requires explicit initialization; there is no automatic refresh.
Analysis exposes `last_successful_sync_at`, the cached source, and snapshot completeness.
After a failed manual refresh, the catalog may contain partially refreshed records;
the last successful timestamp remains unchanged and completeness is false.
Include the last successful sync timestamp in metadata Markdown outputs and responses.
Its `verify_query_update()` performs targeted query-definition read-back and compares
the exact saved SQL, updating only the verified query in SQLite without advancing
the full catalog sync timestamp. Newly created views receive a targeted details read.
The managed inter-location workflow uses cached metadata for planning and verifies
SQL after changes. Generic low-level SDK calls remain available; callers
must use this service for project design operations.

Run `.venv/Scripts/python.exe apps/analytics_metadata.py` on Windows (or the workspace
virtualenv equivalent). Default output is `output/analytics_metadata/<workspace_id>/`
with SQLite, summary and analysis JSON/Markdown exports. The default command reads
the cache without constructing an authenticated client. Add `--sync` to explicitly
refresh remote metadata and workflow mappings. `--view-id` includes workflow
impact and saved SQL for the selected view; `--output` selects another directory.

The explicit registry is `src/workflows/analytics_catalog/registry.py`. Exact names
resolve to IDs within the synchronized workspace; missing/ambiguous references are
reported separately from remote sync errors. Pass `WorkflowViewReference` records
for deployment-specific IDs; no static scan can resolve arbitrary runtime SQL.
The catalog service replaces its registry projection on each sync. Maintain durable
custom registrations in the supplied registry rather than editing SQLite manually.
Metadata sync refreshes definitions, not the source data feeding Zoho Analytics.

- `metadata.sqlite` is the canonical, versioned snapshot and resume state.
- `summary.md` lists counts, view/relationship types, and table column counts.

`Metadata.migrate_json_snapshot()` converts the former expanded JSON layout
without making network requests. After validation, the legacy JSON files can
be removed.

Individual view failures are recorded and do not stop unrelated metadata from
being collected. A snapshot is marked complete only when no object-level errors
remain.

# Related Knowledge

## Folder Organization

Reports and supporting query tables are organized by business function: Sales &
Orders, Receivables & Collections, Purchases & Payables, Inventory & Fulfilment,
GST & Tax, Banking & Cash, Accounting & Finance, Reconciliation, Reference Data,
and Development. Imported source tables retain their connector folders. Brand
and vendor names remain in view names and filters.

Folder moves use the Analytics v2 `views/movetofolder` endpoint. This workspace
rejects multi-view CONFIG parameters with error 8507; compact, single-view
requests work. A successful move can return an empty JSON object, so verify
folder IDs through live inventory read-back rather than relying on response
content. Preserve original folder IDs and checkpoint progress before continuing.
Folder moves do not refresh the canonical metadata cache; cached folder
placements remain historical until an explicitly requested manual sync.

## Detailed General Ledger

Workspace `264324000000002043` contains **detailed general ledger**
(`264324000008493010`). The query left-joins Accrual Transactions (Zoho Books)
to Accounts (Zoho Books) on Account ID, exposing Account Name and Account Type
alongside posting details, debit, credit, and location ID. Its fixed date range
is FY 2025–26: 1 April 2025 inclusive through 1 April 2026 exclusive.
Account Name and Account Type can be filtered in the resulting table.
It does not calculate opening, closing, or running balances.

## Purchase Query Table

The saved `Purchases by Vendor - All Years` query table includes GST-bearing
bills plus GST-bearing expenses less GST-bearing vendor credits, before GST.
Bills require a positive sum of CGST, SGST, IGST and CESS amounts; vendor credits
require positive `GST Present`. Zero-GST bills and commercial credits are
excluded from this GST purchase comparison. GST expenses require a
positive Analytics `Tax Value`; their `Sub Total (BCY)` and document count are
shown separately as `GST Expenses` and `Expense Count`. Draft/void documents
are excluded. Recipient GSTIN comes from the document location, and fiscal
years run April through March. Bills use posting date with bill-date fallback;
expenses use expense date and credits use vendor-credit date.

Supplier grouping prefers vendor PAN, then vendor GSTIN-derived PAN, then
expense GSTIN-derived PAN, with vendor/document identifiers as fallback.
A left vendor join retains GST expenses without a vendor ID. Retain a backup
of the existing SQL and compare a dynamic SQL preview with a fresh saved-table
export when changing the definition.

## Undeposited Funds Deposit Report

Workspace `264324000000002043` contains **Undeposited Funds - Deposit Report**
(`264324000008503041`), backed by **Undeposited Funds - Deposits and Payment Candidates**
(`264324000008503027`) for account `1094368000000000456`. It groups deposit credit
lines by deposit entity ID and date, with total value and ambiguous/unmatched line
counts. Candidate payments match customer, location, full amount and a payment
date on or before deposit date. These are inferred candidates, may recur across
deposits, and do not establish confirmed associations or handle partial/combined
payments. Aggregate each accrual line before aggregating deposits to prevent
candidate joins from inflating totals. Both views are registered consumers.

Zoho reformats saved SQL. Compare SQL tokens while preserving quoted identifiers
and literals, then pass the exact read-back definition to `verify_query_update()`.
The Create Report endpoint supports summary views over a query table.

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [Development Runbook](development-runbook.md).
