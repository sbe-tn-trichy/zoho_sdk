---
type: operations
description: Two-year Schedule III sheet updates and current-year fixed-asset depreciation checks.
---

# NCE document Preparation

Other Expenses note accounts ending in `(GST)` appear first. Both that group
and the remaining accounts retain alphabetical ordering and their amounts.
NCE Interest Expense is assigned by account ID to Note 16 Finance Costs and
linked to P&L row 11 for both years. It is excluded from Note 15; Finance Costs
is included in expense reconciliation, preserving profit and total expenses.

The workbook's manually maintained `checkbox` tab compares entered FY 2025–26
AIS/supporting figures and FY 2024–25 audited financials with statement and note
lines. Column E holds source amounts; F holds documented adjustments; G:I show
expected, live workbook amount and difference; K shows Pending, Match, Review,
or Missing / duplicate. Exact label lookups survive note row movement and reject
missing or duplicate labels. Differences round to two decimal places. AIS credits
must be reconciled to closing receivable balances before expecting equality.
When `sheets.checkbox` and `sheet_ids.checkbox` identify this existing tab,
`--apply` refreshes G/H/I/K formulas using each check's current row and year.
Source amounts E, adjustments F, and evidence J remain untouched, as do custom
combined-line H lookups. This repairs comparisons after rows are moved and
verifies formula read-back and errors in the same atomic statement update.
The backup includes the prior check rows. Header changes and a reached scan limit
fail before writing; `checkbox_row_limit` defaults to 1000.
Preview runs remain read-only and do not read or modify checkbox inputs.
`checkbox_mappings` configures combined note comparisons by exact `year`,
`section`, and `line_item`, with a nonempty unique `note_lines` list. Apply rebuilds
only the matching checkbox H formula, choosing the year's note amount column
and rejecting missing or duplicate labels in the sheet. These mappings do not
change note classifications, statement totals, or Books records. Other custom
lookups remain preserved.
The FY 2024–25 Other Expenses comparison includes Note 15 accounts without
a separate audited expense line, plus Other Expenses. Accounts already covered
by individual or combined audited checks are excluded to avoid double counting.
Its explicit membership lives in `checkbox_mappings`; differences remain visible.
Adjacent formula cells are read as column ranges to keep large check lists
within Google request URL limits.
Newly added or renamed statement/note lines require updating its check list.

[apps/update_statement_schedules.py](../apps/update_statement_schedules.py) prepares
the four-tab financial statement workbook using the public
[workflows.statement_schedules](../src/workflows/statement_schedules/) API.
This runner is separate from the older, differently laid-out statement updater.
The Google workbook identity, Books organization, excluded location, two complete
April–March periods, note classifications and exact statement destination rows
live in the Git-ignored `config/statement-schedules.yaml`. A generic schema/example
is [statement-schedules.example.yaml](../config/statement-schedules.example.yaml).

Run `.venv/bin/python apps/update_statement_schedules.py` for a read-only
live preview. Each period makes one Schedule III P&L and one Schedule III balance
sheet request. With inventory rollforward enabled, one additional balance sheet
at the earlier year's opening date is fetched, five report requests overall.
The later year's opening inventory reuses the earlier year's closing report.
The endpoints' verified default
responses contain no prior-year comparison column, so the runner fetches each
year separately. It checks echoed dates, accrual basis and branch exclusion.
Assets outside the excluded location are read once, with paginated valuation
history used to reconstruct current-year opening WDV. Books is never mutated.

The `notes` configuration assigns schedule paths to note numbers; `account_notes`
overrides individual stable account IDs. Every nonzero account must be classified
or covered by a direct statement input. Accounts use their own totals; repeated
closing rows and parent subtotals are excluded. New accounts are included using
configured section paths. Nonzero unmapped accounts fail instead of disappearing.
Standalone current-year earnings is explicitly included despite lacking an ID.
The bank/cash and stock account overrides correct their presentation when Books
places them under Other Current Assets. A branch-rule echo does not establish
transaction-level exclusion: SBE-named accounts can retain returned balances.

`inventory_rollforward` identifies the purchases and inventory notes; the expense
direct input marked `inventory_changes` receives the calculated movement.
Books' purchases section represents COGS. Net purchases equal COGS minus opening
inventory plus closing inventory; changes in inventories equal COGS minus net
purchases (opening minus closing). Note 13 shows the COGS subtotal and both stock
balances before its calculated net purchases total. Opening stock uses the same
account classifications as closing stock, including ID overrides. Missing or
incorrectly scoped opening reports fail; nonzero source inventory changes fail
to prevent double counting. Both calculated expense lines still reconcile to
COGS and the source profit. Offline snapshots need `balancesheet-opening` in the
earlier period's report bundle.

`inventory_rollforward.opening_stock_overrides` maps financial-year labels to
reviewed nonnegative opening amounts. Source reports are still validated; preview
observations show the override and Books amount. Purchases and inventory movement
use the reviewed opening amount while their combined COGS and profit stay unchanged.

`inventory_rollforward.cogs_reductions` maps a year to `account_id` and `amount`
for an explicit reduction of one purchases-note account. It changes COGS and
increases expected profit by the reviewed amount; opening overrides still affect
the purchases/inventory split separately. Missing accounts and negative or
excessive reductions fail. Preview observations disclose the change and that
Books and balance-sheet earnings are unchanged; these require separate review.

Generated notes manage columns A:C, with current/prior year input values and
subtotal formulas. A note can define ordered `groups` with a `name` and explicit
`account_ids` to aggregate its detail rows. NCE Note 9 uses Cash (CASH-BA, CASH-BD,
Cash-SBE, Petty Cash and Undeposited Funds) and Bank (BD IDFC,
Bharath-Agencies-HDFC, Bharath-Distributors-BOI and HDFC-SBE). Group membership
must be unique, and any ungrouped nonzero account stops preparation for review.
Zero groups remain visible; statement reconciliation still uses the account totals.
NCE Note 7 combines Finished Goods, Inventory Asset, Ledvance Stock and SBE Stock
under Inventory Asset; other stock accounts retain their separate rows.
NCE Note 5 classifies Zeiss Adjustment as Other Current Liabilities.
NCE Note 14 combines Salaries and Employee Wage, Employee Travel Expense and
Zeiss Support Expense under Salaries and Employee Wage for both years. The
salaries checkbox compares that combined note row without adding its members again.
Notes with exactly one displayed detail row omit the redundant Total row;
statement links use that detail row directly. Empty notes retain a zero Total,
and multi-line notes retain SUM totals. The purchases inventory bridge retains
its named COGS subtotal and Net purchases result.
Statement detail rows link to the note balance rows and
note-number hyperlinks target their new headings. Existing statement subtotal
and profit formulas are preserved. Assets A:O contain only the current-year
tables (the period with the latest end date). Table 1 lists asset names, ledger
account names and historical opening WDV, with ledger subtotals. Table 2 links
to those subtotals and shows one row per ledger for additions, depreciation and
closing WDV using posted depreciation expense, plus independent calculation
comparisons. The total links to the correct current-year P&L depreciation cell
and shows the difference explicitly. Calculated depreciation sums individually
rounded and prorated asset calculations; mixed ledger rates are labelled explicitly.
`asset_ledger_overrides` maps a stable asset ID to `account_id` and `account_name`
for reviewed presentation corrections; Elevator is presented under Machinery.
NCE uses `asset_opening_source: ledger`: prior-year Books fixed-asset balances
plus explicitly assigned accumulated depreciation accounts supply opening WDV.
A single eligible opening asset receives its ledger balance; ambiguous multi-asset
allocation or differing register basis fails instead of guessing. Nonzero opening
ledger accounts absent from the register remain visible with missing depreciation
flagged. Reviewed ledger aliases keep register accounts tied to the correct ledger.
For other configurations, `asset_opening_reclassifications` moves reviewed first-day register acquisitions
into opening WDV without changing the depreciation basis. `ledger_only_assets`
includes identified fixed-asset ledger balances absent from the register using
prior/current balance-sheet reads, leaving depreciation blank and warning about
missing rate/history. Books remains unchanged. Missing account identity/name fails before apply. Register reconciliation remains.
 

NCE now selects `asset_layout: reviewed_statement` for the user-reviewed single
statement in A:I. `reviewed_asset_statement` stores explicit start/end dates and
ordered rows (`name`, `opening`, optional `before_cutoff`, `after_cutoff`,
`purchase_date`, `rate` as a fraction, and `depreciation`). Opening-row amounts are reviewed inputs. Current-year scoped register
acquisitions are appended with zero opening, purchase date, cutoff-split additions,
rate and posted depreciation. Optional `opening_asset_id` explicitly matches an
opening row to a register asset. Optional `opening_account_id` also pins its
ledger account; a mismatch fails and verified mappings appear in preview observations. Matching first-day acquisitions equal to the
reviewed opening are treated as imported opening balances and are not added
twice; missing IDs, duplicate assignments or differing basis fail. Other matched
assets must reconcile to their historical opening with no additions. The renderer preserves their
order and depreciation, generates total/closing formulas, and leaves a blank row
before the totals. Optional supplied `total`/`closing` amounts must reconcile
within one paisa. Invalid amounts, duplicate names, excess depreciation and stale
periods fail. Differences against P&L depreciation and Note 6 remain visible in
the preview; this layout does not change statement or Books accounting amounts.
The Markdown preview includes the A:I sheet output with calculated formula
values and totals before the independent register checks. Only A:I is managed for this layout, including stale-row clearing; J:P and native
formatting remain outside its writes. The default `ledger_tables` layout retains
the two register-verification tables above. Reviewed annual inputs must be updated
explicitly before preparing another financial year.

The asset check supports yearly declining depreciation with `prorata_basis`
(including the depreciation start day, divided by actual FY days) or `no_prorata`.
Historical opening WDV comes from valuation history, never today's asset value.
Only posted depreciation affects historical WDV and expense totals; acquisition
is included even when its journal flag is false. Unknown events, incomplete
history, nonzero salvage, straight-line/monthly methods and invalid rates fail
pending a reviewed rule. Small differences can arise from Books' internal
rounding. Register expense and WDV are compared with the full ledger, and
coverage differences are reported rather than posted or forced to agree.
Sheets formulas use integer active-day/FY-day ratios and single-cell SUM syntax
to remain stable under Google's formula normalization during read-back.

Output defaults to `output/statement-schedules/`: `sources.json`, `plan.json`
and `preview.md`, including source capture time and reconciliation observations.
Replay with `--saved output/statement-sheet-source/sources.json`; snapshots must
match configured organization, periods and scope. `--output` accepts an explicit
directory outside input files. These artifacts contain financial data and stay
Git-ignored.

`--apply` needs `GOOGLE_SHEETS_ACCESS_TOKEN` with edit access. The runner verifies
tab names and IDs, bounds and native validation, refuses unexpected statement
formulas (allowing previous generated note links to move), saves
`sheet-before.json`, and compares native `userEnteredValue` with the plan before
writing. Only changed cells are sent in one native batch, with adjacent changed
cells in each row combined. An identical plan sends no write request. Comparisons
distinguish literal text from formulas even when the text is identical, and numeric
values compare numerically. External text stays literal; generated formulas stay formulas.
Only note heading rows (`Note N:`) are bold across Notes A:C; all other managed
note rows are regular, including totals and cleared stale rows. Bold changes are
compared with native effective formatting and written only when different. Other
formatting is preserved. The backup includes native cells and formatting. It verifies
note bold formatting after apply, reads back every changed value/formula and checks
for formula errors before reporting success. Old rows in the managed note/asset
blocks are explicitly blanked; the bounded scan defaults to 500 rows and can be
changed with `managed_row_limit`. Unrelated columns and main subtotal cells are
outside the write set. Layout changes require adapting config before use.
