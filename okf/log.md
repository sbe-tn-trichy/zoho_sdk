# Knowledge Change Log

## 2026-08-10

- Split GSTR-1 draft, sequence, chronology, and e-invoice verification by each location's GST registration (`tax_settings_id`) and added read-only Books location access.
- Corrected GSTR-1 e-invoice verification to use each transaction's nested `einvoice_details` and IRN instead of separate bulk e-invoice endpoints.
- Added a read-only GSTR-1 verification workflow for previous-month invoice and credit-note drafts, financial-year-aware number continuity and chronology, and applicable e-invoice registration status.

## 2026-08-04

- Added single-page and automatically paginated Zoho Books financial-account transaction retrieval through `chart_of_accounts`.
- Added a dry-run-first, checkpointed Creator matched-payment backfill that
  updates reciprocal identifiers on existing Books customer payments without
  creating payments or modifying bank matches.
- Added production-safe Creator collection reconciliation with schema validation, Books customer-payment custom-field provisioning, exact reference/date/amount matching, Analytics-assisted manual exceptions, Creator audit records, dry-run operation, and declared OAuth scope requirements.

## 2026-08-03

- Added form-encoded Zoho Books requests and the `contacts.bulk_update()` public API for updating multiple contacts with one request.
- Added the `contacts.list_customers()` public API, including default active-status filtering, optional filter overrides, and client-side customer-only enforcement for inconsistent live API responses.

## 2026-08-02

- Added 200-row Analytics view pagination and incremental SQLite synchronization
  using remote modification markers, retry-safe sync checkpoints, content
  hashes, deleted-view cleanup, and selective table-column updates.
- Replaced expanded Analytics metadata JSON snapshots with compressed,
  normalized SQLite storage, indexed readers, resumable database state, a
  compact Markdown summary, and an offline legacy migration helper.
- Added resumable Zoho Analytics workspace metadata snapshots, relationship-map generation, local `zoho_analytics_conn` token lookup, and visible `6045`/429 recovery messages.
- Moved business workflows from `src/zoho/workflows` to the parallel top-level `src/workflows` package and removed the `zoho_sdk_advanced` compatibility shim.
- Hardened the Polycab workflow against duplicate uploads and attachments, strict PDF parsing failures, ignored vendor/account inputs, and unsafe Catalyst fallback behavior.
- Restricted Analytics row exports to validated CSV/JSON formats and made workflow dependencies optional and lazily loaded.
- Consolidated the former `zoho_sdk_advanced` business workflows under `workflows` while retaining root and legacy-subpackage compatibility imports.
- Documented the one-way dependency boundary from core transport and service clients to higher-level workflows.
- Added workflow runtime configuration, credential-safety guidance, and complete local validation commands.
- Added Zoho Analytics dynamic SQL export support using asynchronous jobs, polling, and CSV result parsing.
- Established OKF v0.2 maintenance rules and excluded local `.codex` artifacts from version control.
