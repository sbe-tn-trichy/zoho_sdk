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

The snapshot stores raw object responses alongside `catalog.json`, a normalized
catalog, and `relationships.json`, a node-and-edge map covering containment,
data-source, involved-view, lookup-column, and column-dependent relationships.

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
collector writes `manifest.json` after every completed object. If retries are
exhausted, it reports that the download is paused and the next run can resume.

# Snapshot Files

- `workspace.json`, `folders.json`, `datasources.json`, and `views.json`
- `views/<view-id>.json` and `tables/<view-id>.json`
- optional `dependents/<view-id>_<column-id>.json`
- `catalog.json`, `relationships.json`, `errors.json`, and `manifest.json`

Individual view failures are recorded and do not stop unrelated metadata from
being collected. A snapshot is marked complete only when no object-level errors
remain.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [Development Runbook](development-runbook.md).
