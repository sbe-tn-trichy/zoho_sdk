# Knowledge Change Log

## 2026-10-09

- Excluded generic CHQ DEP - CTS CLG1 prefixes and clearing-location suffixes from customer evidence in bank statement categorization, preserving remitter details after a colon.

- Payment review treats history matching multiple customers as an informational note and permits review and acceptance; a unique different historical customer remains blocking.

- Exclude reverse-charge purchases from GSTR-2 comparison totals and queues by default using portal flags, Books RCM evidence, and exact supplier/document counterparts; retain explicit opt-in RCM reconciliation.

- Restricted the vendor-purchase query table to positive GST bill/credit amounts, excluding zero-GST purchases and commercial credits while retaining GST expenses.

- Extended the Analytics vendor-purchase query table with GST-bearing expenses, separate amount/count columns, and supplier-GSTIN fallback for expenses without vendor IDs; validated preview and saved export.

- Stock transfers accept an explicit starting invoice number, check collisions, and verify the saved sequence; empty plans stop before creation.

- Changed paired stock transfer pricing to purchase rate plus 1% markup, retaining two-decimal half-up rounding.

## 2026-10-08

- Registration now maps Books `contact_number` to Creator `Customer_no`; added targeted preview-first backfill with collision checks and read-back verification.

- Verified the live registration form uses `Name`; customer registration now accepts it while retaining legacy `Customer_Name` support.

- Customer registration now creates records by default; explicit `--dry-run` or `dry_run=True` previews without writes.

- Added paired Books/Creator customer registration, dry-run previews, linked IDs and explicit partial-failure recovery.

## 2026-10-07

- Moved dashboard group membership into workflow configuration with validated domain assignments and dynamically derived tabs.

- Support redacted UPI suffix-and-handle history searches and block mixed-customer collisions.

- Added bank-first and Creator-first review tabs with grouped proposed matches and unmatched records.

- Removed the separate Bank Statement Categorization preview dashboard entry; retained the review interface, CLI refresh option, and stable shortcut numbers.

## 2026-10-06

- Scope the Creator-first bank review to online and cheque records without a Books transaction ID; show unmatched records as Not available and keep completed checkpoints outside the default pending view.

- Added a separate workflow catalog, including Bank Statement Categorization under collection reconciliation, with module links and application guidance.

## 2026-10-05

- Added PDF-backed Polycab RMA credit review and checkpointed correction, with explicit labeled references, preserved rounding allocations and reusable download/reference helpers.

- Support regrouping the audited GST asset into fixed assets without changing audited totals or GST payable.

- Allow GST-netted compared asset and liability totals while preserving gross Books snapshots.

- Support pending unmapped operating-expense exclusions in the audited comparison without changing Books net profit or statement totals.

- Show unmatched audited-comparison account balances as absolute amounts with Dr/Cr, reversing the statement section's normal side for negative balances.

- Monthly Analytics GST comparison uses a combined CGST/SGST/IGST total against the following month's verified three cash-tax accounts, excluding CESS.

- Added monthly GST movement comparisons with following-month cash-tax debits, including an Analytics route and explicit payment-proxy and ITC limitations.

- Added read-only GST cash-ledger comparison by tax head, with scoped live reports, saved mode and explicit mismatch tolerance.

## 2026-10-04

- Audited comparison respects a reviewed Sundry Debtors mapping and removes its unmapped warning when configured.

- Unmatched audited-comparison accounts omit balances that round to zero at two decimals; nonzero debit and credit balances remain visible.

- Audited comparison ends with unmatched statement accounts and balances; group mappings cover children while headline totals and residual expenses do not imply account-level matches.

- Audited financials GST Payable now compares output GST minus input GST, including net-credit and zero cases, without changing statement totals.

- Added the live-verified Books Account Transactions report for raw ledger pages (response option 0) and count metadata (option 2), with explicit dates and validated account scope.

- Added optional reviewed P&L account additions to balance-sheet comparison rows, with explicit provenance and unchanged Books report totals.

- Audited comparison renders balance differences with accounting-aware Dr/Cr labels, explains the opposite adjustment direction, and preserves signed numeric results.

- Live trial balance uses an accounts tree with values records; comparison preserves formatted Dr/Cr balances and validates scope fields while tolerating display metadata.

- Audited comparison replaces horizontal P&L with trial balance, retains all account balance columns, and uses configured firm scope for all filtered reports. Saved reruns require a trial-balance snapshot.

## 2026-10-04

- Moved trial-balance firm identities, aliases, default selection and location rules into editable local YAML with a generic example and fail-closed validation.

- Added BD/Bharath Distributors and SBE/Sri Bharath Electricals trial-balance aliases, preserving GSTIN calls and selecting the corresponding SBE exclusion or inclusion.

- Added the Books trial-balance resource method and reviewed GSTIN-scoped helper using an SBE exclusion, with date/basis/rule validation and raw report preservation.

- Added a timezone-qualified creation timestamp beneath the audited comparison report title, separate from Books snapshot retrieval time.

- Promoted audited XLSX P&L, balance-sheet and horizontal stock comparisons into a reusable workflow and read-only CLI with editable YAML, saved snapshot replay and financial validation.

- Switched the Books statement sheet updater to the shared accounting YAML, preserving calculation sections and supporting atomic YAML account-name refresh plus explicit JSON paths.

- Prefer `config/config.json` for runtime configuration, retaining legacy root fallbacks; keep local accounting mappings alongside it with a generic tracked YAML example.

- Consolidated workflow snapshot overlays, atomic JSON/CSV persistence, payment-series validation/read-back, payment evidence matching and ledger reference comparisons in typed core helpers, retaining resource-specific policies and compatibility APIs.

- Preserved dynamic mutation-token routing during 401 refresh retries, bounded negative retry delays, isolated concurrent JSON checkpoint staging with failure cleanup, and fixed Windows UTF-8 input for the payment review JavaScript test.

## 2026-10-03

- Added reviewed Polycab vendor advances for the exact bank narration token, scoped to Sri Bharath Electricals, with live-line validation and unique active vendor/branch resolution.

- Grouped possible GSTIN discrepancy pairs once in the FY report, excluding their sides from the other detailed missing-document queues while preserving monthly reconciliation counts.

- Added supplier and document-level unresolved review queues plus possible GSTIN discrepancy pairs to the GSTR-2 fiscal-year report after cross-month matching.

- Reused bill subtotal and GST from the Analytics snapshot to avoid unnecessary Books detail reads when only the gross total differs.

- Extended fiscal-year GSTR-2 Analytics snapshots and 24-hour Books change overlays to expenses and vendor credits, with fail-closed modified-filter checks and local monthly selection.

## 2026-10-02

- Added GSTR-2 run progress with completed months, elapsed wall time, and start/completion logging for every physical Zoho HTTP attempt, including retries and failures.

- Replaced fiscal-year GSTR-2 full-history Books bill scans with an Analytics bill snapshot plus 24-hour Books modified-bill overlay, preserving posting dates and rejecting stale or incomplete refreshes.
- Added an optional Analytics expense export check to avoid full Books detail reads for unchanged zero-tax expenses during FY reconciliation.

- Added sequential fiscal-year GSTR-2B verification with complete-return validation, unique cross-month document matching, adjusted monthly outputs, and a yearly timing/gap report.

- Extracted payment inspection/renumbering, customer validation and invoice-YAML import into workflows; added strict FY selection, bounded sequence analysis, live-state/checkpoint safeguards and explicit SDK API migrations.

- Added a dry-run bill transaction posting date helper and CLI that skip unchanged dates and verify saved changes.

- Made GST purchase net (bills plus GST expenses less GST vendor credits) the authoritative AIS matching basis; invoice-only figures remain supporting evidence.

- Added read-only AIS master reconciliation with scoped paced Books reads, explicit invoice/net purchase bases, TDS/TCS and tax/refund checks, complete-snapshot replay and CSV/JSON reports.

- Added raw Detailed General Ledger pages through the browser-identified `generalledgerdetails` endpoint, with account rules, 500-row defaults, and bounded pagination with repeated-content detection. OAuth access and response schema remain unverified live.

## 2026-10-01

- Added read-only per-customer invoice discount and payment-allocation verification with CSV exports and discrepancy summaries.

- Added reviewed CASH DEPOSIT cash-to-bank transfers and Salary expenses, with account-ID configuration, payment-match exclusion, live revalidation, and salary multiselect.

- Removed real retry sleeps and Books pacing from mocked unit tests while retaining retry assertions and production limits; verified preview caching and request metrics, and audited existing indexed catalog reads and 200-row pagination.

- Added expense multiselect and sequential confirmed bulk categorization, retaining failed selections for retry.

- Reduced Bank Statement Categorization reads with expiring preview caches, force refresh, conflict-before-invoice checks, empty Analytics result handling, bounded SQL batches, TA account reuse, and completed-request counts; posting retains fresh validation.

- Fixed travel expense account validation to read configured IDs directly; the Books account list omits the active travel account in this organization.

- Configured the bank review travel expense account by ID, with active expense-type validation and an overridable runtime setting.

- Added an Expenses dropdown view for TA expense proposals in Bank Statement Categorization, with search and separate payment controls.

## 2026-09-28

- Mapped audited Fixed Assets to the Books non-current and fixed-asset sections plus Motor Vehicles, with additive section/account comparison support.
- Corrected the filed FY 2024â€“25 GST balance-sheet mappings: output GST is a liability and input GST is an asset, each grouped by CGST, IGST, and SGST Books accounts.
- Included live Books account names beside IDs in the filed balance-sheet comparison CSV's `books_source` column.

## 2026-09-27

- Corrected the inter-branch helper to use the branch-filtered Books General Ledger report: non-SBE FY 2025â€“26 balance is 48,175 credit. The raw register omits that nonzero filtered balance.
- Added a public inter-branch detailed-ledger helper around the paginated Books register SDK method, with validated account and branch scoping; live FY 2025â€“26 read returned 26 included transactions.
- Added a read-only filed FY 2024â€“25 balance-sheet comparison with exact sheet-cell and Books-account mappings, partner capital schedules, CSV output, and explicit unmapped classifications. The Books balance-sheet branch filter requires scope review.
- Persisted the FY 2025â€“26 P&L note cell-to-account mapping and added a focused one-report `--pnl-only` preview/apply path with Note 3 partner-interest read and formula protection.
- Added `is_expand=true` to the Books P&L report request used by the schedule-format helper.
- Populated the live FY 2025â€“26 P&L notes from branch-excluded Books account totals and restored statement-to-note formulas; documented COGS, interest, and miscellaneous classification limits.
- Added a branch-exclusion P&L helper for explicit report dates; the web schedule-format route returned code 5, so the SDK retrieves its figures through the working regular P&L API and verifies applied filters.
- Classified equity ledger interest by offset account and withdrawals by transaction type in the Books statement sheet updater; the residual movement remains explicit and closing balances reconcile.
- Integrated the bulk equity-ledger helper into the Books statement sheet updater, reconciling owner movements to location-scoped opening and closing balance-sheet amounts while preserving closing formulas; added an equity-only run option.
- Added a paginated Zoho Books account-register reader and a bulk-filtered equity-ledger helper; live probing showed the register needs an explicit account-ID query filter even when the ID appears in its path. The web Detailed General Ledger route is not exposed at the corresponding public API path.
- Added a read-only Books-backed split proposal for fully allocated payments spanning multiple document locations, with per-location amounts and source documents.
- Added a grouped apply workflow for the outstanding FY 2025â€“26 vendor payment proposals, with all-series preflight and per-series read-back audit.
- Held payments whose destination-series number conflicts with the current Books location for manual reconciliation instead of proposing an automatic move.
- Added a read-only Books recheck of all FY 2025â€“26 payment proposals that removes payments already at their destination location and saves an observation audit.
- Scoped generated inter-location payment proposal reports to FY 2025â€“26 while retaining FY 2026â€“27 in the live Analytics Query Table.
- Scoped the vendor numbered update proposal to payments requiring a destination series change; same-series location-only mismatches are excluded.
- Corrected vendor payment proposals to preserve an existing destination-series number and reserve new suffixes only for payments changing series.
- Added read-only Books preflight and numbered FY 2025â€“26 proposals for inter-location vendor payments across three destination series.
- Changed customer-payment batch verification to one descending series page for the whole batch, checking each saved ID, number, location, account, date, and amount.
- Added a Books customer-payment multipart update with explicit suppression of automatic number generation, after confirming a one-payment FY 2025â€“26 move retained its chosen number.
- Replaced the all-payment number scan with a one-page Books prefix-filtered descending lookup, checking that Books applied the filter and sort before proposing destination numbers.
- Scoped the customer-payment move script to FY 2025â€“26 by payment date, with a 15-payment batch default and current Books series numbering.
- Added a dry-run-first helper and script for reviewed customer-payment location and number updates in the SBE FY 2025â€“26 series, with current Books preflight, collision checks, and read-back verification.
- Added observed destination payment-number prefixes by location, fiscal year, and payment type to inter-location proposals; final series and unique suffix remain Books preflight requirements.
- Added a read-only all-bank-account payment location proposal report that checks complete allocation locations and holds mixed or clearing-account cases for review.
- Included payment-to-invoice and payment-to-bill location mismatches across all synced bank accounts in the inter-location Analytics Query Table, with bank account ID and name columns; contra pairing remains scoped to the clearing account.
- Expanded the clearing-account Analytics Query Table to include customer payment versus invoice and vendor payment versus bill location mismatches, with an explicit issue type; contra move proposals ignore the new payment-document rows.
- Consolidated inter-location Analytics Query Table generation and updates under a unified workflow function (`sync_inter_location_contra_query_table`) and primary CLI (`apps/manage_inter_location_contra_query_table.py`) while preserving create and update commands as thin compatibility wrappers.
- Extracted domain business logic from CLI apps (`apps/repair_review_payment_allocations.py`, `apps/backfill_online_payment_creator_fields.py`, `apps/export_neoseal_items.py`) into dedicated workflow modules (`workflows.collection_reconciliation.repair`, `workflows.online_payment_creator_backfill`, and `workflows.neoseal_audit.exporter`), restoring strict package hierarchy (`zoho <- workflows <- apps`).
- Centralized payment reference normalization in `workflows.core.matching.normalize_payment_reference` and shared atomic JSON checkpointing in `workflows.core.checkpoint.write_atomic_json`.
- Added regression tests verifying GSTIN grouping/validation, payment reference matching variations, non-finite amount handling, and backward compatibility for `workflows.creator_customer_delete_sync`.

- Added a fast, Analytics-driven customer payment date audit workflow and CLI (`apps/check_customer_payment_dates.py`) using saved Query Table `Customer Payment vs Applied Date Mismatch` (`264324000008269008`) to detect entries where applied date matches neither payment date nor invoice date, plus a safe-by-default updater CLI (`apps/update_invoice_payment_dates.py`) to adjust applied dates to `MAX(Payment Date, Invoice Date)`.

- Added an all-pairs Books preflight and audited apply command for reviewed customer payment location moves, stopping before writes on any verification failure.

- Added a read-only proposal generator for the saved inter-location Query Table; it groups allocated documents and holds uncertain pairs for manual review.

- Expanded the live inter-location Analytics Query Table with allocated invoice and bill locations and document numbers for move decisions.

- Added a dry-run-first publisher for a live Analytics Query Table containing only inter-location contra pairs, retaining match strength and review status.

- Added strict 4-way location verification (bill, vendor payment, invoice, customer payment) for Vendor-Customer clearing account reviews, and added payment-to-document location auditing for general bank accounts (`vendor_payment` vs bill locations, `customer_payment` vs invoice locations).

- Added a read-only FY 2025â€“26/FY 2026â€“27 account contra review that fetches source-document locations, highlights uniquely paired inter-location entries, proposes moves when all allocated documents agree, and optionally cross-checks Zoho Analytics.

- Added a complete Zoho Books chart-of-accounts SQLite snapshot and automatic `account_names` refresh for financial-statement mappings, failing closed on unknown account IDs.

- Made `books_statement_mapping.json` the dedicated, Git-ignored default configuration for the Books financial-statement sheet updater, including its Google spreadsheet ID and required Books location scope, while retaining optional custom mapping paths and spreadsheet-ID overrides. Report requests now explicitly use the custom-date filter and configured location IDs.

## 2026-09-26

- Added a preview-first, account-ID-based workflow for mapping configured Zoho Books P&L and balance sheet reports into the FY 2025â€“26 Google Sheets statement template, with exact-cell and formula guards.

## 2026-09-25

- Excluded zero-tax / commercial vendor credits from Missing in GSTR-2B alerts and categorized them under non-GST documents, ensuring only vendor credits with active GST tax are tracked for portal reconciliation.

- Updated GSTR-2 monthly report filenames to include 3-letter Mon-YYYY and an IST run timestamp suffix (`<Mon>-<YYYY>_<DDMM>_<HHMM>.md`, e.g. `Apr-2025_2509_1417.md`).

- Included reverse-charge Books expenses in matching against RCM portal invoices,
  using detail-only reverse-charge tax while keeping them separate from forward-GST
  expense matching and supplier-filing risk reporting.

- Added a read-only GSTR-3B versus Zoho Books P&L workflow and CLI that compare monthly and FY outward taxable value with the scoped Sales account hierarchy, verify annual reconciliation, and export CSV; COGS is shown separately because GSTR-3B lacks an ordinary purchase total.

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
  call, reducing sheet API calls from 95+ to 3 and execution time to ~2â€“3s while
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
- Renamed the bank-withdrawal workflow to Bankâ€“Vendor Ledger Matching under `workflows.bank_vendor_ledger_matching`, retained `workflows.bank_reconciliation` as a deprecated compatibility alias, and renamed its default output directory and OKF concept.
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
