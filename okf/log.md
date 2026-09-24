# Knowledge Change Log

## 2026-09-24

- Added a readable IST last-run timestamp to each generated GSTR-2 monthly Markdown report.

- Removed amount-only GSTR-2 purchase matching so distinct supplier documents
  with the same value cannot consume each other's Books expense.

## 2026-09-23

- Added a guarded paid-bill update workflow that temporarily unlinks vendor
  payment allocations for reductions, then reapplies payment up to the new
  bill total and leaves any excess as unapplied vendor payment credit.

- Simplified `GSTR2_LOCATION_GSTIN_MAP` to map each recipient GSTIN directly
  to its list of Books location IDs.

- Switched cumulative GSTR-2 category and summary outputs from JSON to CSV,
  preserving month-keyed upserts and migrating existing histories.

- Assigned GSTR-2 bills to return months by transaction posting date, fetching
  across bill dates so later-posted bills remain in scope.

- Organized GSTR-2 output into month-keyed reports and cumulative category JSON
  histories under `Output/GSTR2 Verification`, with reruns replacing an
  existing month's data instead of producing duplicates.

- Replaced runtime GSTR-2 location discovery with a fail-closed static
  `GSTR2_LOCATION_GSTIN_MAP` configuration snapshot, including location names
  and owning GST registrations.

- Scoped GSTR-2 Books bills, expenses, and vendor credits by the recipient GSTIN mapped from Books locations, with incomplete-report protection for unresolved locations.

- Added guarded many-to-one GSTR-2 purchase mappings so a validated consolidated Books bill can account for multiple portal invoices without cluttering missing-item report sections.

- Corrected GSTR-2 Books net-taxable display for entity-level discounts, subtracting pre-tax discounts but not after-tax or already-net item-level discounts.

- Expanded GSTR-2 value-mismatch rows with side-by-side portal and Books taxable and tax amounts, including vendor-credit tax summaries; the CLI now preserves existing reports when core Books fetches fail.

- Corrected GSTR-2 vendor-credit retrieval to use the Books `vendor_credits` response key; the endpoint-name default had silently produced zero credits.

- Expanded GSTR-2 / GSTR-2B verification to reconcile GST-bearing Books expenses alongside bills and vendor credits, using positive forward tax rather than GST registration alone.

- Exposed GSTR-2 / GSTR-2B verification as runnable dashboard entry 17 with a validated JSON file picker and temporary-source cleanup.

## 2026-09-22

- Added GSTR-2 / GSTR-2B verification workflow and CLI runner (`apps/verify_gstr2.py`) to cross-check GST portal purchase data against Zoho Books bills and vendor credits, detecting value mismatches, unrecorded purchases, and Section 16(2)(aa) ITC risks.

- Replaced full-table Analytics export with targeted historical SQL queries using remitter identifiers (UPI VPA, phone, remitter name); supports confirmation, conflict detection, and non-blocking new remitters while scaling gracefully to 100K+ rows.

- Corrected bank-line direction handling to the production convention: debit means deposit and credit means withdrawal. Only credit `/TA` lines receive travel expense proposals.

- Renamed the production review UI to Bank Statement Categorization; added Analytics narration-based customer suggestions for other bank lines and an explicitly approved Employee Travel Expense action for `/TA` withdrawals.

- Show Analytics customer-name suggestions beside ambiguous bank candidates without making them automatically eligible for posting.

- Added Analytics Payment Customer Finder name validation to the production payment review queue; proposals require one matching view row and are rechecked before pushing.

- Removed pandas from the workflow extra after confirming no project code imports it; retained the PDF and spreadsheet dependencies used by specific workflows.

## 2026-09-17

- Removed the standalone ICICI unmatched-entry export and its dashboard entry;
  kept shared bank reference normalization and reserved dashboard number 4.

- Added dashboard tabs for favorites, reconciliation, and workflow categories,
  with browser-persisted favorites and global search.

- Added a shared VS Code folder-open task that launches the existing dashboard
  homepage through the project virtual environment.

## 2026-09-16

- Scoped the Creator payment-ID backfill by the oldest matched Creator payment
  date and a required Books location; added missing-link discovery, sequence-gap
  reporting, and `All_Payments` cross-checks before writes.

- Corrected matched-payment lookup handling for Creator customer lookup values
  and the Books `customerpayments` response shape; used list custom fields for
  dry-run discovery and added configurable checkpoint paths.

- Reconciled missing native payment numbers in Creator `matched` with
  `All_Payments` and blocked detail fallback when a supplied payment number is
  absent from the scoped Books list, removing false competing claims.

- Paced live Books payment requests and retried code-44 rate limits before
  continuing the Creator ID backfill.

- Exposed the Creator-to-Books payment ID backfill as a workflow and added a
  live payment read before writing missing Creator custom fields.

- Added dry-run Creator-to-Books customer beat synchronization using the
  Creator beat display value and the Books `cf_beat` contact custom field.

- Limited the beat allocation page to active Books customers and rechecked
  active status before each Creator Beat update.

- Added a loopback customer beat allocation review page with jurisdiction-scoped
  beat choices and per-customer live validation before Creator updates.

## 2026-09-15

- Added stable count-line IDs and an API sync for Mapping addresses and SKU-keyed QTY/PACK formulas, so Mapping reorder and StockCount row moves can be reconciled without redirecting formulas.

## 2026-09-14

- Consolidated collection response-ID and Books payment payload helpers, moved
  exact scoped SKU lookup into Inventory helpers, and reused finite decimal
  parsing for duplicate payment checks.

- Hardened authenticated URL overrides to approved HTTPS Zoho hosts, redacted
  missing-token OAuth errors, and made empty HTTP error responses raise normally.

- Rebuilt and verified every mapped StockCount QTY formula to use the corresponding Mapping SKU and Flat available quantity in column E.

- Removed sort order, group, and subgroup from the Neoseal Flat schema; item ID now starts in column A and packing is in column L.

- The Neoseal Flat refresh now validates the full existing header order and numeric item IDs before writing, preventing duplicate appends from shifted columns.

- Optimized NeoSeal Flat stock count upsert to use bulk truncate and add: cleared
  data rows via `worksheet.records.delete` with `criteria='"item_id" != \'\''` to
  leave headers intact, then re-added all merged items in a single `worksheet.records.add`
  call, reducing sheet API calls from 95+ to 3 and execution time to ~2–3s while
  preserving manual counts, remarks, and unapproved missing items.

- Made NeoSeal Flat reads inspect the full grid after deletions: Zoho's tabular
  fetch stops at a blank row and previously hid later items, causing duplicates.
  Approved deletions now process individual row indices from bottom to top.

- Added the Inventory item's `cf_pack_size` custom-field value to the trailing
  `packing` column in NeoSeal Flat upserts, preserving existing column positions.

- Added a post-upsert report of Flat items absent from the current tracked
  Inventory fetch, plus an exact-ID deletion command that requires separate
  approval and revalidates missing status before deleting.

- Limited the NeoSeal Flat stock-count run to active Inventory items whose
  catalog `track_inventory` flag is true, filtering before bulk detail fetch.

- Corrected Zoho Sheet record updates to send the required `data` parameter,
  enabling item-ID-based Flat stock-count updates.

- Changed the NeoSeal stock-count command to an ungrouped Flat-only Inventory
  quantity upsert keyed by item ID; existing rows retain manual fields, missing
  items are appended, and StockCount/Mapping are left untouched.

- Added a custom `StockCount` reconciliation operation that sets QTY to zero for
  product lines without a SKU-to-cell mapping while preserving mapped values and
  section headings.

- Moved the Neoseal `Mapping` sheet's Name field to column C and sourced each
  mapped item's name from its product row in `StockCount`; unmapped items keep
  blank Cell and Name values, and refreshes reject missing page labels.

- Added permanent CLI runner `apps/sync_creator_customers.py` for reconciling
  customer records between Books and Creator, configurable branch/status filtering,
  safe dry-run defaults, and connected it to entry 10 in `apps/dashboard.py`.
- Updated the Neoseal `Mapping` worksheet to link 90 active Inventory items
  to their target `QTY` columns in the customized dual-column `StockCount` layout
  (Column `C` for Left table, Column `H` for Right table) while keeping the `AVL`
  columns (`D` and `I`) blank. Added `clear_range` to `ZohoSheetAPI`, updated
  `CUSTOM_STOCK_COUNT_MAPPING` in `workflows.neoseal_stock_count`, preserved
  intentional unmapped entries (`cell=""`), and aggregated available quantities
  for multi-variant consolidated count rows.
- Added `apps/format_stock_count.py` and `format_custom_stock_count_sheet` API
  in `workflows.neoseal_stock_count` to automatically merge category header cells
  (`A:D` and `F:I`), align text and numeric columns, and apply clean borders across
  the dual-column `StockCount` sheet in Zoho Sheet.
- Reorganized configuration files (`zoho_config.example.json` and local profiles)
  into module/workflow sections (`core`, `dashboard`, `creator`, `neoseal`,
  `polycab`, `fan`, `zeiss`, `banking`) with automatic key flattening and prefix aliasing.

- Moved Neoseal stock count worksheet names (`Sheet1`, `Flat`, `Mapping`) to
  configuration files (`zoho_config.json` / `config.json`) with individual and
  grouped mapping settings, and enabled project-root `config.json` recognition.
- Migrated minimum Python runtime requirement and CI validation matrix to
  Python 3.14 exclusively in `pyproject.toml` and GitHub Actions workflows.

## 2026-09-13

- Added a `Mapping` worksheet to the Neoseal stock count workbook establishing
  SKU-to-cell coordinates for `Sheet1` and populating stock quantities directly
  into mapped count cells while preserving custom cell assignments.

- Restored the full one-row-per-item Neoseal detail table in the workbook's `Flat` worksheet while retaining the grouped count view in `Sheet1`.

- Changed the Neoseal Zoho Sheet count to a vertical group/subgroup/item layout modeled on the workbook sample, with distinct bold heading sizes and row-index replacement on refresh.

- Changed Neoseal stock count to fetch active Inventory items only and publish
  the ordered count table to a managed Zoho Sheet worksheet while preserving
  matching manual physical counts and remarks across refreshes.

- Added a read-only Neoseal stock-count workflow and dashboard entry using scoped
  Inventory item details, explicit quantity fields, suggested groups/subgroups,
  custom shelf ordering, and CSV/Markdown count sheets.

- Migrated Neoseal tools, Polycab RSO lookup, item helpers, and YAML sales-order
  item resolution/creation to Inventory. Removed the Books item resource and
  implicit Books-token fallback for Inventory mutations; mixed-service APIs now
  require an injected Inventory client.

- Established Zoho Inventory as the required API for item and inventory operations,
  retaining purchase-account scoping for vendor catalogs.

## 2026-09-09

- Added profile-level dashboard workflow inclusion and exclusion controls with validated stable domain IDs.
- Removed the deprecated `workflows.bank_reconciliation` compatibility package;
  bank-to-vendor matching is available only from
  `workflows.bank_vendor_ledger_matching`.
- Expanded the operations home page into a searchable catalogue covering every domain workflow, using a single-screen left-side launcher list and persistent right-side output panel.
- Organized GSTR-1 verification output by GSTIN with nested reports for every
  fetched Books location, including locations with no target-month documents.

## 2026-09-08

- Added a stock-transfer preflight guard requiring the start date to be on or after the latest invoice date in the explicitly selected number series.
- Rounded stock-transfer rates to two decimal places after applying the fixed 3% markup.
- Added exact invoice-to-bill rounding alignment and verified `bill_created` journal recovery for paired stock transfers.

## 2026-09-07

- Extended paired stock transfers with a fixed 3% cost markup, maximum final-invoice threshold, quantity splitting, and inclusive date-range scheduling that excludes Sundays.

- Added `get_bins_for_items` (and `getBinsForItems`) helper in `zoho.helpers.bins` to query item stock across warehouse bins from Zoho Analytics with SKU, item ID, and positive-stock filtering.
- Added Inventory bulk item details and a paired Books replenishment workflow with purchase-account scope, GSTIN validation, commitment-aware stock caps, dry-run plans, and partial-execution journals.

## 2026-09-06

- Added customer status and Branch custom-field filtering for Creator sync; excluded Books customers remain protected from deletion.

- Renamed Creator customer deletion sync to customer sync with configurable field comparison, creates, updates, and guarded deletions; legacy imports now use full reconciliation.

## 2026-09-04

- Added a `Possible matches` payment-review filter and explicit candidate selection for bank lines whose date and amount match while the reference differs, with live uncategorized/date/amount revalidation before pushing.
- Added a dedicated payment-review `Ambiguous` filter and retained all competing bank-line details for safe human inspection without enabling ambiguous pushes.
- Grouped all payment-review Creator report link names under one `PAYMENT_CREATOR_REPORTS` JSON/environment setting while preserving the existing production names as defaults.
- Cheque review matching now compares the final four digits of cheque numbers against individual numeric runs in Books bank references and narrations.

## 2026-09-03

- Added `apps/apply_neoseal_name_updates.py` and `workflows.neoseal_audit.naming_rules`
  to apply reviewed nomenclature, SKU overrides, and SI unit standardizations
  directly to Zoho Books items. Features include safe-by-default dry-run,
  automatic pre-update JSON backup snapshots, duplicate collision avoidance, and
  audit reporting.
- Added `NEOSEAL_PRICE_LIST_GOOGLE_SHEET_ID` to the active configuration,
  template, and workflow configuration API for the Neoseal price-list source.
- Extended the purchase-account-scoped Neoseal item audit with optional
  SKU-based price-list verification, non-positive margin detection, pack-size
  and MRP completeness checks, and missing vendor-alias detection. The CLI
  accepts a price-list CSV containing `sku` plus `price`, `rate`, or
  `selling_price`.
- Recorded the NeoSeal solvent SKU convention `Grade-Volume-Type-Color-PackageMaterial` and retained SKU identity during reviewed catalog-name migration.

## 2026-09-02

- Added the `neoseal_audit` domain workflow and `apps/audit_neoseal_items.py` CLI
  for automated catalog data quality, detecting legacy duplicates and Tin vs Can
  packaging twins, auditing item nomenclature (`GS Plus`, tape parenthetical
  casing), validating user-generated SKU structures, and flagging unassigned or
  catch-all Zoho item groups.
- Completed the JSON configuration template, added a configured Creator payment
  app link name, and added coverage that prevents public configuration keys from
  drifting out of the template.
- Enforced active-only purchase-account catalog exports so inactive items never enter nomenclature reviews or downstream update inputs.
- Added explicit NeoSeal and fan purchase-account configuration keys for safely scoping item-catalog workflows.
- Added `purchase_account_id` item catalog scoping policy to `AGENTS.md` and `okf/zoho-books.md`, and extended `zoho.helpers.items` (`fetch_items_lookup`, `find_item_by_sku_or_name`, `fetch_items_by_purchase_account`) to prevent cross-vendor catalog collisions in vendor workflows.
- Extracted reusable domain-agnostic workflow functions into `zoho.helpers` overlay modules (`fetch_open_invoices`, `fetch_open_bills`, `find_bill_by_number`, `normalize_cheque_number`, `allocate_documents_fifo` in `transactions`, `get_financial_year_range` in `dates`, `extract_bank_withdrawals` and `extract_bank_deposits` in `accounts`) and refactored workflows (`collection_reconciliation`, `vendor_customer_offset`, `gstr1_verification`, `polycab_credit_memos`, `bank_vendor_ledger_matching`) to eliminate duplicate document fetching, FIFO allocation, cheque normalization, and bank line filtering.

- Made tenant configuration fail closed with project-before-user precedence and

  replaced the hardcoded Creator owner with explicit `CREATOR_OWNER_NAME`
  configuration.
- Hardened Creator/Books payment backfills with duplicate-identifier detection,
  batch-write confirmation, response and readback verification, per-row atomic
  checkpoints, and resumable verified outcomes.
- Closed failed streamed HTTP responses, retained endpoint context on ordinary
  failures, and deduplicated concurrent 401 token refreshes.
- Prevented strong and weak bank-ledger matches when both populated references
  conflict, and made workflow root exports lazy for base-only installations.
- Added Python 3.8/current CI coverage for full workflow extras and a separate
  base-install import check.

## 2026-09-01

- Expanded `zoho.helpers` higher-level composite overlay layer (`contacts`, `items`, `custom_fields`, `files`, `gst`, `dates`, `accounts`, `transactions`) and refactored multiple workflows (`vendor_customer_offset`, `duplicate_payment_check`, `gstr1_verification`, `polycab_rso`, `creator_customer_delete_sync`, `collection_reconciliation`) to eliminate duplicate GST normalization, bank account lookups, date parsing, custom field provisioning, and response unwrapping.
- Restored permanent operational utilities under `apps/`, repaired package-safe
  application imports, made reconciliation identity-safe and ambiguity-aware,
  added vendor-credit skipping and malformed-date handling, hardened token
  refresh and output paths, and restored workflow subpackage exports.
- Consolidated repository policy in `AGENTS.md`, made `GEMINI.md` defer to it,
  and reconciled guidance for documentation authority, tests, compatibility
  aliases, typed workflow contracts, and safe output paths; refreshed the stale
  scope and version at the top of `INDEX.md`.
- Extracted web templates from Python scripts to `apps/static/` (`dashboard.html`, `payment_review.html`) and standardized application bootstrap via `apps/_bootstrap.py`.
- Added explicit PEP 484 parameter signatures across matching wrappers (`bank_vendor_ledger_matching` and `vendor_ledger_reconciliation`), added `TypedDict` data contracts in `collection_reconciliation.types`, and decomposed invoice allocation and cheque joining logic into `allocator.py` and `cheques.py`.
- Renamed the bank-withdrawal workflow to Bank–Vendor Ledger Matching under `workflows.bank_vendor_ledger_matching`, retained `workflows.bank_reconciliation` as a deprecated compatibility alias, and renamed its default output directory and OKF concept.
- Extracted a shared `BaseResource` base class (`src/zoho/base_resource.py`) eliminating duplicate CRUD and streaming pagination implementations across Books and Inventory.
- Centralized client factory instantiation across `apps/` through `workflows.core.auth`, and unified string/decimal conversion helpers (`to_decimal`, `to_text`) in `workflows.core.matching`.
- Reorganized project entry points into a dedicated `apps/` layer for web servers, dashboards, and CLI runners (`dashboard.py`, `payment_review.py`, `run_collection_reconciliation.py`, `check_duplicate_payments.py`, `export_icici_unmatched.py`, `import_polycab_rso.py`, `register_customer.py`), keeping `src/workflows/` strictly as pure domain libraries.
- Established an ephemeral 24-hour retention lifespan for `scripts/` and cleaned up legacy one-off backfill scripts.
- Added a read-only purchase-account-scoped NeoSeal Books catalog export and a
  filtered missing-alias CSV so vendor item names can be recorded in native item
  aliases before future import matching.
- Repaired the shared request contract across all concrete clients, routed POST mutations through Catalyst mutation authentication, preserved an explicit read-only Sheet POST exception, and added regression coverage.
- Consolidated binary downloads behind a close-safe streaming writer, prevented completion callbacks from materializing streamed bodies, normalized cross-platform filenames, and restored declared Python 3.8-compatible WorkDrive annotations.
- Repaired stale HTTP/path tests and the Sheet test fixture, and normalized worksheet metadata responses to the documented list of names.
- Excluded void invoices and credit notes from GSTR-1 sequence violations
  while retaining their document numbers as occupied sequence positions.

## 2026-08-31

- Fixed the dashboard payment reconciliation preview to refresh the production
  `Online_Payments` and `Cheques` review state instead of invoking the absent
  `Collection_Records`/`Reconciliation_Audit_Log` Creator schema.
- Fixed VS Code folder-open homepage startup with a health-checked, duplicate-safe dashboard launcher.
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
