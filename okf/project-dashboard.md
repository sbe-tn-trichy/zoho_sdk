---
type: Runbook
title: Project Operations Dashboard
description: Local numbered launcher for frequently used Zoho SDK workflows.
tags: [operations, dashboard, workflows, safety]
status: active
---

# Project Operations Dashboard

`apps/dashboard.py` serves a local startup page at
`http://127.0.0.1:8750`. The single-screen home page uses a compact workflow
list on the left and a persistent run-output panel on the right. Tabs across the
top show Favorites, Reconciliation, the available workflow categories, and All.
The star on each workflow adds or removes it from Favorites; selections persist
in that browser. Search spans all workflows by name, number, or category.
Workflow number 4 is retired so other shortcut numbers remain stable.
Safe, fully configured operations have a
stable number and can be launched from their card (or by entering the exact
number and pressing Enter). Operations requiring a source file, business
parameters, or confirmation remain visible with a concise setup requirement
instead of being launched with guessed inputs. The page displays process state
and a bounded recent-output log. Workflows that serve their own local interface
expose an Open link after launch.

GSTR-2 verification is an exception to the generic setup-only treatment for
file-dependent workflows: entry 17 provides a JSON file field, validates the
selected file, stores it only in a temporary file for the duration of the run,
and deletes that temporary source after the verifier exits.

Workflow visibility is configured in the active `zoho_config.json` profile:

```json
"dashboard_workflows": {
  "include": [],
  "exclude": ["polycab_credit_memos", "vendor_customer_offset"]
}
```

An empty `include` list includes every registered domain. If `include` contains
IDs, only those domains are shown. `exclude` is applied last and therefore wins
when an ID is present in both lists. Supported IDs are
`collection_reconciliation`,
`creator_customer_sync`, `duplicate_payment_check`, `gstr1_verification`,
`gstr2_verification`,
`neoseal_audit`, `neoseal_stock_count`, `polycab_credit_memos`, `polycab_rso`, `stock_transfer`,
`vendor_customer_offset`, and `vendor_ledger_reconciliation`. Configuration
with unknown IDs or incorrectly typed values fails at dashboard startup rather
than silently hiding the wrong operation.

The numbered Bank Statement Categorization preview uses
`apps/payment_review.py --refresh-only`. It reads the production
Creator `Online_Payments` and `Cheques` reports, rebuilds the local review
state, including other uncategorized bank lines and suggestions, prints a compact
entry summary, and exits without writing to Zoho. The
generic `Collection_Records` schema workflow is not registered because that
form is not part of the production `order-management-new` Creator app.

# Safety Model

The dashboard binds only to a loopback address and mutation requests require a
random per-process token embedded in the page. It executes argument arrays from
a fixed registry without a shell and accepts no browser-supplied command or
arguments. Registry commands use read-only or dry-run defaults; live flags such
as `--execute` and `--allow-batch` are intentionally absent. The payment review
workflow can create changes only after the user separately confirms them in
its own token-protected review interface.

# Running

Opening this repository as a trusted folder in VS Code runs the
`Open project dashboard` task automatically. It uses the project `.venv`,
starts the dashboard if needed, and opens the page in the default browser.
The same task can be run manually through **Tasks: Run Task**.

From the repository root:

```bash
python apps/dashboard.py
```

See [Development Runbook](development-runbook.md) and
[Bank Statement Categorization](collection-reconciliation.md).
