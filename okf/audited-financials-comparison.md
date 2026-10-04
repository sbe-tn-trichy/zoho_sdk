---
type: operations
description: Read-only audited XLSX comparison with saved or live Zoho Books financial reports.
---

# Audited financials comparison

`net_gst_in_balance_sheet_totals: true` removes gross input CGST/SGST/IGST
from compared asset and liability totals, presenting GST only as the net
output-minus-input liability. Saved Books snapshots remain unchanged. The
audited GST asset remains an unmapped source amount unless
`audited_gst_asset_to_fixed_assets: true` regroups B15 into audited Fixed
Assets B6. That presentation leaves audited total assets and GST payable
unchanged, preserves source values, and renders B15 as regrouped rather than unmapped.

`excluded_pnl_expense_accounts` lists pending unmapped expenses excluded from
the operating-expense and residual Other Expenses comparisons. Their balances
remain in Books net profit and appear in the unmatched-account table with a
mapping-pending explanation; excluding them does not reclassify transactions.

The final table lists statement accounts with account IDs that lack an audited
mapping, excluding balances that round to zero at two decimals and including residual Other Expenses accounts. Mapped
account groups cover their children; headline statement totals do not. Coverage
is limited to the fetched P&L and balance-sheet reports, not the entire catalog.
Unmatched balances display absolute amounts with Dr/Cr according to their
statement section: assets and expenses are debit-normal, liabilities/equity
and income are credit-normal. Negative balances reverse the side.

`apps/compare_audited_financials.py` runs the library workflow in
`workflows.audited_financials`. It compares P&L and balance-sheet values and
renders Markdown with all vertical COGS leaves, including zero balances, plus
trial-balance account opening balances, debits, credits and closing balances. Differences are Books minus audited, calculated with Decimal.
Rendered differences use absolute amounts with Dr/Cr according to the reviewed
template's accounting nature: assets and expenses are debit-normal; income,
profit, liabilities and capital are credit-normal. Negative differences reverse
the side; zero has no side. These describe balance differences, and an adjustment
to align Books with audited values would use the opposite side. Numeric result
fields retain signed Books-minus-audited values.
Each Markdown report shows its creation timestamp beneath the title in ISO 8601
format with the runtime's local UTC offset. This records report generation time,
including saved-data reruns; Books retrieval provenance remains separate.

The supported audited workbook layout is the reviewed `Trading & P&L` and
`Balance Sheet` tabs with current values in column B. Core statement row numbers
are fixed to that template; another layout needs an explicit adapter. Cached
formula values are read without recalculating or modifying the workbook.

Run with the workspace Python:

```powershell
.venv/Scripts/python.exe apps/compare_audited_financials.py --source 'C:/path/audited.xlsx' --saved
```

`--saved` loads five JSON snapshots from `--snapshots` without constructing a
client or accessing the network: `profitandloss`, `balancesheet`, their
`-all-locations` counterparts, and `trialbalance`. Omit `--saved` to
fetch all five via read-only Books GET requests. The app creates clients through
the core auth factory. `--from-date` and `--to-date` select the comparison period;
defaults are FY 2024–25. Saved report dates and accrual basis must match.

`--mapping` defaults to the local `config/accounting-mapping.yaml`. Calculations
use account coefficients, derived calculations, or exact section paths. Expense
and balance-sheet mapping keys identify column-B rows.
Optional `balance_sheet_pnl_accounts` maps the same row keys to P&L accounts
whose signed totals are added to the balance-sheet account sum as a reviewed
regrouping. The row must exist in `balance_sheet_accounts`; unknown accounts
fail explicitly. This changes the line comparison only, not Books report totals
or P&L expense presentation.
Mapped Sundry Debtors B9 renders its configured accounts and is excluded from
the unmatched-account table; the unmapped warning appears only without a mapping.

The existing Google Sheet configuration sections may coexist and are left untouched. Review the generic
`config/accounting-mapping.example.yaml` before using it with another organization.

Live scope defaults to `config/firm-reports.yaml` (or `--firm-config` /
`FIRM_REPORT_CONFIG`). `--firm` selects a configured alias or GSTIN. The same
rule applies to P&L, balance sheet and trial balance. Repeated `--exclude-location`
arguments override that scope. Saved mode uses original snapshot scope and
requires `trialbalance.json`; older horizontal snapshots need a fresh live run.
Matching filtered and unfiltered totals remain unresolved scope evidence.

`--output` sets the Markdown destination; otherwise it uses
`audited-financials-vs-books-fy24-25.md` in the snapshot directory. Choose an explicit
output name for another FY. Source-cell snapshots and live API responses also
go into that directory using shared atomic writers. The app rejects output paths
that overwrite its source workbook, mapping or Books JSON through Markdown output.

GST Payable B26 compares Output CGST/IGST/SGST minus Input CGST/IGST/SGST.
Negative results represent net input credit. Audited GST asset B15 stays separate
and is not deducted again from B26; Books statement totals are unchanged.

The workflow checks audited totals, trading-cost arithmetic, balance-sheet
balance and Books profit arithmetic. Circular calculations and duplicate expense
allocations fail rather than silently double counting. GST and sundry-debtor
lines without confirmed mappings remain visible for review. Trial balance rows
use `name`, `opening_balance`, `net_debit`, `net_credit`, `closing_balance`,
with nested `account_transactions` or the live `accounts` tree and one `values` record per account. Formatted values preserve Dr/Cr signs. Missing columns fail explicitly. Dr/Cr
values are preserved rather than interpreted as inventory costs. Stock and gross
purchases need reviewed ledger mappings; the workflow no longer fetches horizontal
P&L or constructs its inventory roll-forward. Neither source
files nor Books transactions are changed.

The older [filed balance-sheet comparison](it-balance-sheet-comparison.md) remains
available for its separate Google Sheet/source-cell template.
