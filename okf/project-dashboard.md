---
type: Runbook
title: Project Operations Dashboard
description: Local numbered launcher for frequently used Zoho SDK workflows.
tags: [operations, dashboard, workflows, safety]
status: active
---

# Project Operations Dashboard

`apps/dashboard.py` serves a local startup page at
`http://127.0.0.1:8750`. Each frequently used operation has a stable number and
can be launched from its card or by entering that number and pressing Enter.
The page displays process state and a bounded recent-output log. Workflows that
serve their own local interface expose an Open link after launch.

The numbered payment reconciliation preview uses
`apps/payment_review.py --refresh-only`. It reads the production
Creator `Online_Payments` and `Cheques` reports, rebuilds the local review
state, prints a compact entry summary, and exits without writing to Zoho. The
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

From the repository root:

```bash
python apps/dashboard.py
```

See [Development Runbook](development-runbook.md) and
[Creator Collection Reconciliation](collection-reconciliation.md).
