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

# Online Payments Human Review

`scripts/review_online_payments.py` serves a loopback-only review queue for the
production Creator `Online_Payments` report. It maps `Payment_Amount`,
`Reference`, and the `Customer_Name` lookup to reconciliation values, resolving
the lookup through `All_Customers1.Customer_Id` before any Books payment is
proposed.

Only a unique date, amount, and reference match is eligible for acceptance.
The browser UI presents Creator and bank values side by side. Rejection changes
only the atomic local state file. `Accept & Push` revalidates that the bank line
is still uncategorized and refreshes the customer's open Books invoices. The
payment is allocated oldest-due-first before Books creation, then its ID is
checkpointed, the bank line is matched, and the ID is written into Creator's
`Books_Transaction_Id`. Repeated acceptance of a fully pushed entry is
idempotent. Entries without a unique match or any open customer invoice cannot
be accepted, preventing the entire amount from becoming unused credit.

The review row shows the proposed invoice numbers, due dates, balances, and
amounts applied. The preview reuses one invoice query per customer during a
refresh, but acceptance always queries invoices again so it uses current Books
balances. Allocation may span multiple invoices. When their total balance is
less than the payment, Books receives all possible allocations and only the
displayed excess remains unused credit.

The HTTP server binds only to a loopback address and mutation requests require
both an explicit confirmation body and a random per-process review token. The
queue state is stored at
`output/collection_reconciliation/online_payments_review.json` by default.
The UI supports selecting every ready proposal and confirming one bulk action.
Bulk acceptance fetches the current uncategorized bank set once, then processes
the selected payments sequentially so failures remain isolated and Books API
rate limits are respected.

The default queue combines uncategorized transactions from the configured HDFC,
ICICI, and IDFC Books accounts. Each proposal retains the originating bank name
and account ID; the UI displays the bank in its own column, and an accepted
payment is created and matched through that specific account. A transaction is
never consumed by more than one Creator payment in the same refresh.

The same queue combines Creator's `Online_Payments` and `Cheques` reports.
Online rows use `Payment_Date` and Books mode `banktransfer`; cheque rows use
`All_Cheque_Details.Presented_Date` and Books mode `check`. The detail row is
joined to `Cheques` by normalized cheque number plus customer; the join must be
unique and the presented date must be populated. This prevents a cheque that
has not yet been presented from matching merely because its issue date is up
to 90 days old. Each entry retains its source report so the final
`Books_Transaction_Id` checkpoint is written through the correct Creator
record via the canonical `All_Payments` report. The workflow validates the
Creator response and reads the record back with all fields before marking the
queue entry pushed. The checkpoint writes both the Books payment ID to
`Books_Transaction_Id` and the human-readable Books payment number to the
Creator `PaymentNo` (`Payment#`) field. A failed Creator checkpoint retains the completed
`bank_matched` stage, so retry reuses the existing Books payment and only
retries the Creator write. The UI shows the payment type separately from the bank name. Online
matching remains same-day by default. Cheque matching allows a seven-day bank
clearing window from the presented date while still requiring exact amount and
reference.

Books can identify a single-invoice customer payment in the bank-match candidate
response by its invoice-application ID rather than by the parent customer-payment
ID. The review workflow verifies that application ID by reading the checkpointed
parent payment, submits the candidate ID returned by Books for matching, and
continues to store the parent payment ID in Creator. A retry reuses the existing
parent payment and never creates a duplicate.

Historical review-tool payments can be repaired with
`scripts/backfill_review_creator_checkpoints.py`. It resolves the Books payment
number from each checkpointed Books payment ID, updates both Creator fields,
reads the record back, and saves resumable per-record results. Dry-run is the
default; live writes require `--execute` and are capped by `--max-writes` unless
explicitly set to zero.

`scripts/backfill_online_payment_creator_fields.py` discovers additional
Creator `Online_Payments` records that already have a corresponding Books
customer payment. It only accepts a unique exact customer-ID, date, amount, and
reference match (or a consistent existing Books identifier), then writes and
verifies `Books_Transaction_Id` and `PaymentNo`. Missing, incomplete, and
ambiguous records are reported without mutation. Canonical all-field Creator
records are used so hidden checkpoint columns remain visible to the matcher,
and ownership is checked across the full `All_Payments` dataset so a Books
payment already linked to another Creator record is never reused even when the
owner has disappeared from the filtered `Online_Payments` report.
Dry-run is the default.

The long-running review server supplies Books and Creator token-refresh
callbacks backed by the configured HTTP token broker. A 401 response refreshes
the affected service token and retries the request once. Authorization failure
during the pre-push bank snapshot creates no payment; an individually attempted
entry is left retryable with no Books checkpoint.

Legacy queue payments created before invoice allocation can be repaired with
`scripts/repair_review_payment_allocations.py`. Dry-run is the default. Execute
mode updates the existing Books payment rather than replacing it, preserves any
existing invoice applications, allocates only the live `unused_amount`
oldest-due-first, and reads the payment back after every update. An atomic JSON
checkpoint records planned, repaired, already-allocated, no-open-invoice, and
failed outcomes so the operation is safely repeatable.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), [Zoho Books Client](zoho-books.md), and [Development Runbook](development-runbook.md).
