---
type: operations
description: Read-only comparison of the filed FY 2024-25 income-tax balance sheet with Zoho Books.
---

# Filed balance-sheet comparison

`apps/compare_it_balance_sheet.py` compares the filed balance sheet in the
`P&L,BS 25-Client Data` tab with the Books accrual balance sheet as of
31 March 2025. The reviewed mapping lives in
`examples/it_balance_sheet_fy2425.mapping.json`; it uses exact filed cells and
stable Books account IDs or section paths. The four partner closing capital
balances are included. The source-cell snapshot in
`output/it_balance_sheet_fy2425.source.json` is generated/local data and is
ignored by Git. The CSV result is written to `output/`.
For account-ID mappings, `books_source` includes each ID and the account name
returned by the Books balance-sheet report.

Run `.venv/bin/python apps/compare_it_balance_sheet.py` to compare the captured
filed values against current Books. Add `--live-sheet` and set
`GOOGLE_SHEETS_ACCESS_TOKEN` to reread the original Google Sheet before
comparison. Both modes only read the sheet and Books. The app validates the
Books date, accrual basis, and echoed branch-exclusion rule. It refuses a filed
snapshot for a different sheet or date and checks that the two filed totals
balance. `UNMAPPED` lines have no defensible direct Books account counterpart;
they are retained in the CSV for manual classification.

The Books balance-sheet API echoed the SBE exclusion rule during the initial
comparison, but the result still contained SBE-named cash and stock accounts
and returned the same total as a request with `location_ids`. Treat all
differences as provisional until the Books report's branch scope is verified.
In particular, the filed partner balances include allocated profit whereas
Books shows separate current-year earnings; compare the partner schedules
before treating the capital variance as an error.

The filed `B50` GST Payable line maps to Books Output CGST, Output IGST, and
Output SGST liability accounts. The filed asset-side `D54` GST line maps to
Books Input CGST, Input IGST, and Input SGST asset accounts; it is not the GST
cash ledger. The FY 2024–25 comparison matches output GST exactly and input GST
within ₹0.02.

The filed Fixed Assets line combines the Books `Assets / Non Current Assets`
and `Assets / Fixed Assets` sections with the Motor Vehicles account under
`Assets / Other Assets`. The comparison supports adding section paths and
account IDs on one mapped line. For FY 2024–25, the API returned ₹0,
₹1,47,809.30, and ₹62,539.77 respectively; their ₹2,10,349.07 total is
₹73,887.09 below the audited Fixed Assets amount.
