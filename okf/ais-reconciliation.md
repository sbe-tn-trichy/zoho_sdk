---
type: Workflow
title: AIS Master and Zoho Books Reconciliation
description: Read-only AIS IT workbook reconciliation with explicit purchase bases and replayable Books snapshots.
---

# AIS comparison

`apps/compare_ais.py` reads the AIS IT export layout containing year-prefixed
Source totals, TDS TCS, GST sales, GST purchases, Tax payments and Refunds tabs.
The reusable APIs are exported by `workflows.ais_reconciliation`.

```powershell
& .venv/Scripts/python.exe apps/compare_ais.py 'C:\path\AIS.xlsx'
```

The CLI uses the configured Books organization and Bharath Distributors' existing
Sales account / excluded SBE location defaults. Other organizations must override
`--org-id`, `--sales-account-id` and `--exclude-location-id`. The recipient GSTIN
is inferred from active purchase rows, or validated with `--gstin`. Multiple
recipient registrations are rejected. The P&L adapter requires exactly the
configured other-registration location; it refuses a broader scope it cannot
safely express using the existing GSTR-3B comparison API.

Outputs default to `output/ais_reconciliation/`: a complete Books snapshot,
`report_data.json`, detailed Excel-safe CSV tables and `summary.md`. No Books
transactions are created or changed. XLSX presentation is a separate artifact
authoring step; the Python workflow does not require an Excel library or Node.

## Efficiency and verification

Collection uses 200-row pages, paced at 2.1 seconds by default, with a configurable
250-request ceiling. List schema, pagination completeness, repeated pages and
ledger account/date scope are validated. Only input GST/TCS and TDS/TCS/Advance
Tax ledgers are scanned. Bank requests cover merged seven-day windows around
AIS tax payments and refunds. It does not fan out across invoice details or
download customer payments or unrelated income/bank ledgers. Purchase and
posting-date evidence is indexed by PAN/month; optional payment evidence is
indexed by contact/date. Existing GSTR-3B P&L scope and month-to-FY checks are
reused, with cached Chart of Accounts during collection. Analytics is not
required for this backend; no unverified Analytics schema or refresh state is
treated as live Books evidence.

Collection failure or a request-budget breach does not produce a new complete
snapshot/report. Existing output from a prior run may remain. A complete saved
snapshot can be replayed without authentication or network reads:

```powershell
& .venv/Scripts/python.exe apps/compare_ais.py 'C:\path\AIS.xlsx' --snapshot output/ais_reconciliation/books_snapshot.json
```

Replay validates organization identity, date range, completeness and required
datasets. Reports disclose the original capture timestamp; replay is not a live
refresh. There is no partial-page resume mechanism. A failed live collection
must be rerun after resolving the failure.

## Comparison meaning

Active AIS rows are the master; inactive rows remain as audit evidence. Supplier
GST registrations are combined by PAN/month. Rows without PAN/GSTIN remain
unresolved, and zero-valued rows without purchases are not missing purchases.
The main purchase comparison uses ordinary bills plus GST expenses less
tax-bearing vendor credits, before GST. Invoice-only values are supporting detail
and cannot independently qualify as a match. Commercial credits and
Books `credit_note_vendor` bill entities are shown separately. A supplier/month
gap cannot identify a missing invoice because this AIS layout has no invoice
numbers. A basis match cannot certify invoice completeness.

Bill taxable bases are reconstructed as gross plus TDS less input GST and TCS.
Round-off and adjustments remain in that estimate; unusual RCM or adjustment
documents need detail review. Tax-bearing vendor credits are classified using
gross less pre-tax line value; exceptional adjustments need document review.
Tolerance is one rupee per active purchase aggregate row and one rupee for sales
and tax credits. Invoice-date and posting-date values are both disclosed.

TDS/TCS reconciliation compares new receivable debits with active AIS tax amounts,
not net settlements. Source mapping uses PAN when supplied, otherwise normalized
exact contact names and all contacts sharing a PAN. Ambiguous/unallocated sources
remain review items. TDS/TCS reporting bases overlap GST totals and must not be
added to purchases or sales. Same-date base candidates are supplementary evidence;
customer-payment candidates are available only if the caller's snapshot supplies
optional `customer_payments` data.

Tax payment/refund matches are amount/date candidates requiring narration/CIN
review. Closest-date candidates within seven days are retained, ambiguous matches
are unresolved, and a selected ledger entry cannot be reused for another AIS row.
Master source totals are checked separately against active detail sums.
