---
type: workflow
---

# Unearned Revenue Review

Run `.venv/bin/python apps/find_unearned_revenue.py` for a read-only Analytics
review of account `1094368000000000617`. Override `--account-id`, `--workspace-id`,
`--catalog-dir` or `--output` as needed. The catalog defaults to
`workspace_metadata/<workspace-id>`; the report defaults to
`output/unearned_revenue.json`. An explicit absolute output path is supported.

The command uses `AnalyticsCatalog` cached SQLite metadata and reports its last
successful sync timestamp. It does not refresh metadata or connector data and
makes no Books requests. Source references are owned by the Analytics registry.

`workflows.review_unearned_revenue_analytics` reads the account, positive unused
customer payments with customer names, and all available accrual posting groups
for the account. Explicit SQL aliases preserve column labels across joined
exports. Ledger groups are aggregated before matching Entity IDs to Payment IDs,
so payment joins cannot multiply ledger totals. The report contains each payment,
customer totals in base currency, account credits less debits, the difference
from unused payments, and raw posting groups for investigation. Invalid amounts,
missing or duplicate payment identities, ambiguous accounts and query failures
abort before replacing the report. A previous report may remain; check its time.

Entity ID matches are evidence, not a verified allocation relationship. Unmatched
unused payments remain candidates. Account accrual totals may depend on imported
opening entries and connector completeness. Journals, refunds, opening balances
and source synchronization timing can explain differences. Analytics may lag
Books; this is a current imported-data review, not a historical as-of report.

The earlier `workflows.find_unused_customer_payments` Books scan remains available
as a library function for compatibility and explicit live-detail verification;
it is no longer used by the command. It validates every payment detail at
half-second intervals and keeps payment-currency totals separate.

The Analytics export was verified live on 2026-10-21. Joined columns need explicit
SQL aliases, and monetary exports may include currency-code prefixes and comma
grouping. Aggregated ledger values can contain floating-point residue; round
base-currency presentation to the currency precision.
