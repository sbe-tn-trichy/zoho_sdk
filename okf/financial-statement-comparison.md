---
type: operations
description: Read-only Google financial statement cells versus OAuth Books schedule reports.
---

# Financial statement comparison

`apps/compare_statement_sheet.py` compares the linked FY 2024–25 Google Sheet's
two-sided P&L and balance-sheet layout with the Books schedule data endpoints.
The reusable API is exported from `workflows.financial_statement_comparison`.
Its explicit JSON mapping in `examples/financial_statement_fy2425.mapping.json`
lists all numeric statement cells, account terms and source arithmetic checks.
Review classifications before interpreting differences as posting errors.

Run with `.venv/Scripts/python.exe apps/compare_statement_sheet.py` and set
`GOOGLE_SHEETS_ACCESS_TOKEN` for live Google reads. Zoho clients come from the
core auth factory. All external requests are reads; neither source is edited.
For offline replay use `--saved --sheet-snapshot
output/sheet-schedule-comparison/sheet-cells.json`. Without `--saved`, an explicit
sheet snapshot can be compared with fresh Books reports. Snapshot spreadsheet
identity and period must match the mapping. Both live and saved Books responses
are checked for dates, accrual basis and the echoed branch exclusion.

The workflow calls `reports/scheduleprofitandloss` and
`reports/schedulebalancesheet`, verified with OAuth. Explicit custom dates avoid
relative-year drift. The balance sheet echoes only its as-of date. Raw JSON
responses remain separate from comparison results. Repeated `section=true`
schedule account rows are excluded, account terms use own totals, and explicit
`include_children` selects `total_sub_account` for a parent subtotal. Exact
section paths and signed multipliers support reviewed aggregation. Missing
sources are UNMAPPED, ambiguous sources fail, and no missing amount becomes zero.

The default `output/sheet-schedule-comparison/` contains `report.md`,
`comparison.json`, the two schedule JSON snapshots and captured sheet cells.
The Markdown report groups mismatches first, then unmapped lines and matches,
with counts and the original statement order preserved within each group.
Mismatches are subdivided into liabilities and equities, assets, and P&L/other
lines using this workbook's Balance Sheet columns B and D.
`--output` accepts an explicit directory, including an absolute path; output
files are checked against mapping and source input paths before writing.
Tolerance defaults to INR 1 and must be finite and nonnegative. Source line
sums and the two sides of each statement must balance within INR 0.01.

Opening stock uses the schedule balance sheet's `ASSETS / 2. Current Assets /
b. Inventories` total as of **31 March 2025**, per the user's explicit mapping
instruction for this workbook. It uses `period: current` and reuses the
current balance-sheet snapshot; the date is shown beside the Books source.
For other reviewed mappings, terms marked `period: opening` trigger one
additional balance-sheet read with the same branch scope, saved separately in
`schedulebalancesheet-opening.json`. Offline replay validates its as-of date
and requires this snapshot. The default opening-stock mapping does not use
the prior year-end snapshot.

Other Expenses uses `remaining_expense_path` to sum account own totals within
`IV. Expenses / 7. Other Expenses`, excluding names, IDs and section paths
already assigned to other statement lines. The report lists component amounts;
new accounts are included on reruns, closing rows and parent subtotals are not.
Gross purchases need additional reviewed ledger mappings. P&L trading totals do not directly correspond to schedule
revenue totals. The audited P&L's Net Profit cell B20 is profit **before** tax
per the user's clarification, and maps to `IX. Profit before tax (VII - VIII)`;
it must not be compared with schedule profit after tax. The report displays
this qualification alongside the mapping. Tax is disclosed separately from
the source profit line. Capital, advance tax and net profit can differ because of
profit allocation and tax presentation. The report's branch-rule echo is
scope evidence, not proof of transaction-level exclusion: SBE-named balances
can remain in returned account figures. This workflow does not silently
net GST or reclassify audited amounts to force agreement.
