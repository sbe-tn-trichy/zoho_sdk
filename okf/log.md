# Knowledge Change Log

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
