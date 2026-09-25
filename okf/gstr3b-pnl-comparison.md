---
type: Workflow
title: GSTR-3B and Books P&L Comparison
description: Read-only monthly and FY comparison of filed GSTR-3B outward taxable value against Zoho Books Sales account hierarchy.
---

# GSTR-3B and Books P&L Comparison

`workflows.gstr3b_pnl_comparison.compare_gstr3b_to_pnl()` accepts a combined JSON
object with `filing_year` and exactly twelve filed monthly `returns`. It compares
Table 3.1(a) outward taxable value with the Zoho Books P&L total for a specified
Sales account and all of its descendants. The workflow discovers descendants
from Chart of Accounts, then requests accrual-basis P&L for each month and the
full FY using the same excluded Books location rule. It verifies that the API
applied the requested dates and rule and that monthly Sales and COGS add to the
independent FY report before any CSV is written.

The application entry point is `apps/compare_gstr3b_pnl.py`:

```bash
.venv/bin/python apps/compare_gstr3b_pnl.py /path/to/combined-gstr3b.json
```

Defaults reproduce the Bharath Distributors comparison: Sales account
`1094368000000000486` and excluded SBE location `1094368000044509446`. Override
either with `--sales-account-id` or `--exclude-location-id`. The default CSV is
`output/gstr3b_vs_books_pnl_<FY>.csv`; `--output` accepts another path. The
workflow makes read-only Books requests. The CLI prints the annual variance and
months with a difference. CSV values are in INR, with variance defined as Books
Sales minus GSTR-3B taxable value. Differences within ₹1.00 are labeled `MATCH`
by default; `--tolerance` changes that threshold.

The CSV includes Books P&L Cost of Goods Sold for context. This is not purchases
booked during the period. GSTR-3B does not contain an ordinary purchase total,
so its purchase-comparison column explicitly says the values are not comparable.
Use GSTR-2B or a purchase register for purchase reconciliation.
