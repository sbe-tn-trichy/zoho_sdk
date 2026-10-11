---
type: operations
description: Two-year Schedule III sheet updates and independent fixed-asset depreciation checks.
---

# Statement schedules updater

[apps/update_statement_schedules.py](../apps/update_statement_schedules.py) prepares
the four-tab financial statement workbook using the public
[workflows.statement_schedules](../src/workflows/statement_schedules/) API.
This runner is separate from the older, differently laid-out statement updater.
The Google workbook identity, Books organization, excluded location, two complete
April–March periods, note classifications and exact statement destination rows
live in the Git-ignored `config/statement-schedules.yaml`. A generic schema/example
is [statement-schedules.example.yaml](../config/statement-schedules.example.yaml).

Run `.venv/Scripts/python.exe apps/update_statement_schedules.py` for a read-only
live preview. Each period makes one Schedule III P&L and one Schedule III balance
sheet request, four report requests overall. The endpoints' verified default
responses contain no prior-year comparison column, so the runner fetches each
year separately. It checks echoed dates, accrual basis and branch exclusion.
Assets outside the excluded location are read once, with paginated valuation
history reused across both years. Books is never mutated.

The `notes` configuration assigns schedule paths to note numbers; `account_notes`
overrides individual stable account IDs. Every nonzero account must be classified
or covered by a direct statement input. Accounts use their own totals; repeated
closing rows and parent subtotals are excluded. New accounts are included using
configured section paths. Nonzero unmapped accounts fail instead of disappearing.
Standalone current-year earnings is explicitly included despite lacking an ID.
The bank/cash and stock account overrides correct their presentation when Books
places them under Other Current Assets. A branch-rule echo does not establish
transaction-level exclusion: SBE-named accounts can retain returned balances.

Generated notes manage columns A:C, with current/prior year input values and
subtotal formulas. Statement detail rows link to the dynamic note totals and
note-number hyperlinks target their new headings. Existing statement subtotal
and profit formulas are preserved. Assets A:O contain separate current/prior
year tables with independent depreciation, posted depreciation, differences,
historical WDV, method and location. DOP is presented as Date of purchase.

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
formulas, saves `sheet-before.json`, and writes a single native batch using only
`userEnteredValue`. External text stays literal; generated formulas stay formulas.
Formatting is preserved. It reads back every changed value/formula and checks
for formula errors before reporting success. Old rows in the managed note/asset
blocks are explicitly blanked; the bounded scan defaults to 500 rows and can be
changed with `managed_row_limit`. Unrelated columns and main subtotal cells are
outside the write set. Layout changes require adapting config before use.
