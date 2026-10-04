---
type: workflow
---
# GST cash-ledger comparison

`apps/check_gst_cash_ledger.py` compares CGST, SGST, IGST and CESS Tax cash-ledger
closing balances to Output minus Input accounts using accrual balance-sheet data.
Interest and late fees are excluded. Differences are cash minus expected; default
tolerance is INR 0.01. Missing or ambiguous accounts fail rather than imply zero.
Negative net input credit is retained. Payments and set-offs can affect equality;
the report flags balance mismatches without proving filing or posting errors.

Defaults are BD and FY 2024–25. `--firm`, `--from-date`, `--to-date`, `--tolerance`
and `--output` are configurable. Live reads validate report date and configured
firm location scope. `--saved PATH` reads a saved balance-sheet JSON without network
and uses its original scope and date. Output is `output/gst-cash-ledger/report.md`
plus the balance-sheet snapshot. No Books transactions are changed.

`apps/check_monthly_gst_analytics.py` uses Analytics accrual postings, grouped by
calendar month and GST account within configured firm location scope. Defaults
cover FY 2025–26 and the following April payment month. It compares monthly net
combined CGST/SGST/IGST output credits less input debits with the following month's
cash Tax gross debits. CESS is excluded from the combined comparison. The cash
account IDs are verified against the Analytics catalog before querying results.
Known catalog accounts without monthly postings are zero; missing or duplicate
catalog accounts fail. ITC cross-utilisation and carry-forward are not simulated.
`--start-month`, `--end-month`, `--firm` and `--output` control each run.
`apps/check_monthly_gst.py` provides the equivalent Books trial-balance route.
