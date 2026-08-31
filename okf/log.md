# Knowledge Change Log

## 2026-08-31

- Fixed payment-review bank matching for single-invoice customer payments when Books exposes the invoice-application ID instead of the parent payment ID, including duplicate-safe retries.
- Added sensitive parameter log redaction preserving last 4 characters (`mask_sensitive_value`, `sanitize_log_params`) in `src/zoho/security.py` and `BaseZohoClient`.
- Added thread-safe token refresh synchronization with `threading.Lock` across worker threads in `BaseZohoClient`.
- Added structured attributes (`status_code`, `error_code`, `response_data`, `endpoint`, `retry_after`) to `ZohoError` and sanitized raw HTML gateway responses.
- Added generator-based pagination (`list_iter`) across Books and Inventory `BaseResource` to stream records page-by-page.
- Implemented direct-to-disk chunked binary streaming across WorkDrive, Mail attachments, Books statements, and GSTR reports.
- Fixed `Bills.update` to allow partial payload updates (`check_required=False`).
- Added `raise_on_error` option to `ZohoCliqAPI.send_notification` and typed error handling in `ZohoSheetAPI`.

## 2026-08-29

- Added HTTP connection pooling and persistent session reuse (`requests.Session`) to `BaseZohoClient` with universal timeout defaults across all services.
- Added rate-limit pacing and 429 backoff retry handling to `GST._fetch_details_concurrently` and `CustomerValidator.validate_customer_data`.
- Added in-memory SKU lookup caching in `SalesOrders.create_from_yaml` to prevent duplicate API calls per line item.
- Added server-side date filter propagation (`date_start`, `date_end`) to `DuplicatePaymentChecker.run`.
- Added an exact-match Online Payments discovery backfill that identifies existing Books customer payments, verifies both Creator Books checkpoint fields, and blocks Books payments already owned by another Creator record.
- Added a checkpointed, verified backfill for populating Creator `Books_Transaction_Id` and `PaymentNo` from every historical payment-review Books checkpoint.

## 2026-08-28

- Added the human-readable Books customer-payment number to the verified Creator checkpoint through the `PaymentNo` (`Payment#`) field.
- Hardened payment-review Creator checkpoints with canonical-report writes, all-fields read-back verification, application-level response validation, and duplicate-safe Creator-only retries after a completed bank match.
- Added a loopback-only numbered project operations dashboard with an allowlisted safe-default workflow registry, live process status, bounded logs, and local UI links.
- Added `zoho.security` with `sanitize_filename()` and `resolve_output_path()` to neutralize path traversal attacks across Mail attachments, WorkDrive files, Books contact/vendor statements, and GST report downloads.
- Removed hardcoded tenant entity IDs and accounts from library defaults.
- Implemented multi-tier configuration loading in `workflows.core.config` supporting process environment variables, local `.env`, project `zoho_config.json`, and user home configuration (`~/.config/zoho/config.json`).
- Added `zoho_config.example.json` configuration template and ignored `.zoho_cache.json` in `.gitignore`.

## 2026-08-27

- Changed cheque reconciliation to use the uniquely joined
  `All_Cheque_Details.Presented_Date` instead of the cheque issue date; cheques
  without a unique presented-detail row are not eligible for matching.
- Added a checkpointed repair utility for applying legacy customer-payment
  unused credits to open invoices in place, with oldest-due-first allocation
  and post-update verification.
- Added oldest-due-first open-invoice allocation to reviewed customer payments,
  including visible allocation previews, confirmation-time balance refresh,
  excess-credit disclosure, and a no-open-invoice push block.
- Added a persistent, loopback-only human review queue for the live Creator
  `Online_Payments` report, with local rejection and individually confirmed,
  checkpointed Books customer-payment creation and bank matching.
- Added select-all and single-confirmation bulk acceptance with one shared live
  bank snapshot and isolated sequential push results.
- Combined HDFC, ICICI, and IDFC uncategorized transactions in one payment
  review page with explicit bank labels and account-correct accepted pushes.
- Included Creator `Cheques` beside `Online_Payments`, using cheque dates,
  Books check-mode payments, source-report-aware Creator updates, and a visible
  payment-type column.
- Added automatic Books and Creator access-token refresh and one-time retry for
  long-running review sessions.
- Added a cheque-specific seven-day clearing-date tolerance while retaining
  exact amount and reference requirements.

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

## 2026-08-15

- Added `workflows.creator_customer_delete_sync` workflow for unidirectional deletion reconciliation of Zoho Creator customer records missing from Zoho Books, including `Customer_Id` field linkage, case-insensitive key resolution, dry-run safety, deletion limits, soft-delete option, and audit JSON output.

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
