---
type: Process
title: Bank–Vendor Ledger Matching
description: Books bank-withdrawal matching against vendor payments or external vendor-ledger receipts, including reference normalization and read-only output behavior.
tags: [books, banking, reconciliation, icici, upi]
sources:
  - id: bank-matcher
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/bank_vendor_ledger_matching/_matcher.py
    title: Bank–vendor ledger matcher
    author: team:sbe-tn-trichy
    last_modified: 2026-08-13
status: active
---

# Bank–Vendor Ledger Matching

`workflows.bank_vendor_ledger_matching` reads Zoho Books bank transactions and
matches withdrawals one-to-one against either Books vendor payments or receipts
from a cleaned external vendor ledger. It returns exact, strong, weak,
ambiguous, and unmatched groups without applying matches in Books. The former
`workflows.bank_reconciliation` import remains available as a deprecated
compatibility alias.

# Match Passes

Exact matches require reference, amount, and a date within the configured
tolerance. Strong matches require exact amount and date when a reference is
missing on at least one side. Weak matches allow the configured amount
tolerance and date tolerance under the same missing-reference rule. Populated
but contradictory references are never accepted by the weaker passes.

Matching uses internal row positions rather than external transaction IDs, so
missing or duplicated IDs cannot hide an unmatched record. A candidate is
accepted only when it is unique from both sides; competing equal candidates are
returned in `ambiguous_matches` for manual review instead of being selected by
API order. Amounts are compared as decimal values. Start-only and end-only date
filters are supported independently, and invalid dates remain visible as
unmatched records.

# Bank Reference Normalization

Most accounts use the first populated Books field from `reference_number`,
`reference`, and `cheque_number`. For the configured ICICI bank account, UPI
imports can place a short statement reference in `reference_number` and the
actual payment reference in a narration shaped as `UPI/<12 digits>/...`.
Matching therefore uses those leading 12 digits for ICICI UPI lines.
Non-UPI ICICI lines and all other bank accounts keep the normal Books field
fallback. Raw transaction dictionaries remain unchanged in reconciliation
results.

The same normalization is used by
[Creator Collection Reconciliation](collection-reconciliation.md) when it
matches pending collections and creates manual-resolution collection records.

# ICICI Unmatched Export

Run `apps/export_icici_unmatched.py` to fetch the configured ICICI
account's current `Status.Uncategorized` transactions and write
`output/bank_vendor_ledger_matching/icici_unmatched_transactions.csv`. The audit CSV
includes both the raw Books `reference_number` and the normalized
reconciliation reference, along with a `reference_source` indicator. Because
the source is live Books state, row counts can change between runs as bank
transactions are categorized.
