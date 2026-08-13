---
type: Process
title: Bank Reconciliation
description: Books bank transaction matching, reference normalization, match confidence, and read-only output behavior.
tags: [books, banking, reconciliation, icici, upi]
sources:
  - id: bank-matcher
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/bank_reconciliation/_matcher.py
    title: Bank reconciliation matcher
    author: team:sbe-tn-trichy
    last_modified: 2026-08-13
status: active
---

# Bank Reconciliation

`workflows.bank_reconciliation` reads Zoho Books bank transactions and matches
bank lines one-to-one against either Books vendor payments or receipts from a
cleaned external vendor ledger. It returns exact, strong, weak, and unmatched
groups without applying matches in Books.

# Match Passes

Exact matches require reference, amount, and a date within the configured
tolerance. Strong matches require exact amount and date without a reference.
Weak matches allow the configured amount tolerance and date tolerance.

# Bank Reference Normalization

Most accounts use the first populated Books field from `reference_number`,
`reference`, and `cheque_number`. For the configured ICICI bank account, UPI
imports can place a short statement reference in `reference_number` and the
actual payment reference in a narration shaped as `UPI/<12 digits>/...`.
Reconciliation therefore uses those leading 12 digits for ICICI UPI lines.
Non-UPI ICICI lines and all other bank accounts keep the normal Books field
fallback. Raw transaction dictionaries remain unchanged in reconciliation
results.

The same normalization is used by
[Creator Collection Reconciliation](collection-reconciliation.md) when it
matches pending collections and creates manual-resolution collection records.

# ICICI Unmatched Export

Run `scripts/export_icici_unmatched_csv.py` to fetch the configured ICICI
account's current `Status.Uncategorized` transactions and write
`output/bank_reconciliation/icici_unmatched_transactions.csv`. The audit CSV
includes both the raw Books `reference_number` and the normalized
reconciliation reference, along with a `reference_source` indicator. Because
the source is live Books state, row counts can change between runs as bank
transactions are categorized.
