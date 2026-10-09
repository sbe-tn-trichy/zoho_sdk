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

`sync_workspace()` fetches the lightweight view inventory in pages of 200 and
compares each view's `lastModifiedTime` with its successfully synchronized
marker in SQLite. It fetches details and table metadata only for new or changed
views, removes deleted views, and reconstructs relationships from the local
snapshot. Separate discovered and synchronized markers ensure a failed request
is retried on the next run. SHA-256 content hashes prevent unnecessary row and
column rewrites when the remote timestamp changes without a metadata change.

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

- `metadata.sqlite` is the canonical, versioned snapshot and resume state.
- `summary.md` lists counts, view/relationship types, and table column counts.

`Metadata.migrate_json_snapshot()` converts the former expanded JSON layout
without making network requests. After validation, the legacy JSON files can
be removed.

Individual view failures are recorded and do not stop unrelated metadata from
being collected. A snapshot is marked complete only when no object-level errors
remain.

# Related Knowledge

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

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [Development Runbook](development-runbook.md).
