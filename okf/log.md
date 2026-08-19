# Knowledge Change Log

## 2026-08-17

- Added Polycab RSO PDF parsing and idempotent Zoho Books sales-order import,
  stopping at the first total, resolving existing SKUs, assigning the Sri
  Bharath Electricals location, and attaching the source PDF.
- Added approved Books SKU replacements for Polycab RSO codes `FTANSST033P`
  and `FCEECST303M`, plus unavailable code `LDO0119012`.
- Added a read-only Books API workflow and CLI report for exact duplicate
  customer payments grouped by customer ID, payment date, and amount.
- Made the duplicate-payment output a searchable, print-friendly HTML report
  with summary cards and a row-level review table.
- Changed the default duplicate-payment report to a compact Markdown layout
  grouped by customer and date with reference-and-amount bullets.

## 2026-08-13

- Added a live ICICI unmatched-transaction CSV export with raw and normalized reference audit columns.
- Normalized ICICI UPI bank references from the leading 12-digit narration component for bank and collection reconciliation while preserving Zoho reference fallbacks.

## 2026-08-12

- Excluded non-payable document states, including void invoices with historical balances, from offset allocation.
- Capped bill-specific offset payment references at the live Books limit of 50 characters.
- Added explicit single-vendor scoping for controlled vendor-customer offset runs.
- Split multi-bill vendor-customer offsets into one same-dated customer/vendor payment pair per participating vendor bill.
- Added the vendor-customer offset workflow for unique-GSTIN linked contacts, oldest-due-first invoice and bill allocation, dry-run safety, and compensating rollback.

## 2026-08-11

- Polycab vendor-credit creation now sends the configured location ID explicitly for single-credit and batch processing.

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
