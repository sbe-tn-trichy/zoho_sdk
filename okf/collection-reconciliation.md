---
type: Concept
title: Creator Collection Reconciliation
description: Safe Creator-to-Books collection matching with Analytics-assisted manual exceptions.
tags: [creator, books, analytics, collections, reconciliation, audit]
sources:
  - id: collection-reconciler
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/collection_reconciliation/reconciler.py
    title: Collection reconciliation workflow
    author: team:sbe-tn-trichy
    last_modified: 2026-08-04
status: active
---

# Collection Reconciliation Workflow

`workflows.collection_reconciliation` reconciles pending collection records in
Zoho Creator against uncategorized incoming bank lines in Zoho Books. It is a
high-level workflow and receives Creator, Books, and optional Analytics clients
through dependency injection.

The workflow requires an exact reference match, either in the Books reference
field or within the bank narration, in addition to date and amount checks. Date
and amount tolerances are configurable. Multiple matching bank lines are never
selected automatically. Each bank line can be consumed at most once per run.

When no safe match exists, the workflow can run a configured Analytics SQL
query and return customer suggestions without automatically posting them. A
selected suggestion is applied through `resolve_manual()`, which creates the
Creator collection, categorizes the Books bank line as a customer payment, and
then confirms the Creator record.

# Schema Contract

The `Collection_Records` Creator form requires `Record_ID`, `Payment_Date`,
`Amount`, `Payment_Mode`, `Reference_Number`, `Customer_Name`,
`Reconciliation_Status`, and `Zoho_Books_Payment_ID` fields. Creator provides a
read-only field metadata API, so the SDK validates this contract but does not
attempt to mutate Creator form design.

The `Reconciliation_Audit_Log` form requires `Creator_Record_ID`, `Stage`,
`Message`, `Payload`, and `Occurred_At`. Failed matches, ambiguous matches, and
mutation failures are written there. Audit-write failures are logged without
hiding the original reconciliation result.

Books customer-payment custom fields `Creator Record ID` (string) and
`Creator Payment ID` (number) must both be unique. They can be validated or explicitly created through
`validate_schema(create_missing_books_fields=True)`. Automatic creation is
never enabled implicitly.

# Mutation Safety

`CollectionReconciliationConfig(dry_run=True)` performs reads and matching but
does not create, update, categorize, or audit records. In live mode, Books is
created first and its ID is saved on the still-Pending Creator record. The bank
line is then matched and Creator is marked `Confirmed`. If matching fails, the
next run reuses the saved payment ID instead of creating a duplicate. Every
result separates confirmed, unmatched, and failed records. If the final Creator
confirmation fails after a Books match, the workflow attempts to unmatch the
bank line so the next scheduled run can retry safely.

The workflow declares its required OAuth scopes through
`REQUIRED_OAUTH_SCOPES`; `missing_oauth_scopes()` compares them with a granted
scope set. Tokens and authorization headers are never included in audit data.

# Scheduling

Call `reconcile_collections()` from the deployment scheduler or webhook worker.
Scheduling is intentionally outside the SDK so runtime credentials, retry
policy, concurrency, and organization selection remain deployment-controlled.

# Existing Payment Link Backfill

`scripts/backfill_creator_matched_payments.py` traverses Creator's `matched`
payment report and resolves an existing Books customer payment by native Books
payment ID/number or by an exact unique date, amount, reference, and customer
combination. It then populates the unique `Creator Record ID` and `Creator
Payment ID` custom fields on that existing payment.

The script never creates customer payments and never changes bank-transaction
matches. Dry-run is the default. Writes require `--execute`; multi-record writes
also require `--allow-batch` and are capped by `--max-writes` unless explicitly
set to zero. JSON/CSV results and an atomic per-record checkpoint make runs
auditable and restartable. Conflicting identifiers, missing payments, and
ambiguous matches are never written automatically.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), [Zoho Books Client](zoho-books.md), and [Development Runbook](development-runbook.md).
