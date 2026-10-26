---
type: Concept
title: Bank Statement Categorization
description: Creator payment matching, Analytics-assisted bank suggestions, and reviewed TA expense categorization.
tags: [creator, books, analytics, collections, reconciliation, audit]
sources:
  - id: collection-reconciler
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/collection_reconciliation/reconciler.py
    title: Collection reconciliation workflow
    author: team:sbe-tn-trichy
    last_modified: 2026-08-04
status: active
---

# Bank Statement Categorization Workflow

`workflows.collection_reconciliation` reconciles pending collection records in
Zoho Creator against uncategorized incoming bank lines in Zoho Books. It is a
high-level workflow and receives Creator, Books, and optional Analytics clients
through dependency injection.

The automatic reconciler and online review service share nested response-ID
extraction and Books customer-payment payload construction within this workflow
package. Each caller still supplies its own payment-mode and invoice-allocation
policy.

The workflow requires an exact reference match, either in the Books reference
field or within the bank narration, in addition to date and amount checks. Date
and amount tolerances are configurable. Multiple matching bank lines are never
selected automatically. Each bank line can be consumed at most once per run.

Automatic reconciliation normalizes each bank transaction once per run, indexing
occupied dates and sorted absolute amounts. Candidate searches use inclusive
date/amount tolerance bounds before reference and narration checks. Duplicate
bank rows retain ambiguity and used transaction IDs remain excluded. This index
is limited to the automatic reconciler; the human review and live posting paths
retain their independent validation rules. Non-finite tolerances and bank amounts
are rejected rather than participating in financial matching.

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

`workflows.creator_books_payment_link` powers
`apps/backfill_creator_matched_payments.py`, which traverses Creator's `matched`
payment report and resolves an existing Books customer payment by native Books
payment ID/number or by an exact unique date, amount, reference, and customer
combination. It then populates the unique `Creator Record ID` and `Creator
Payment ID` custom fields on that existing payment.
The workflow reads each resolved payment directly from Books before classifying
its current custom fields. Missing Creator identifiers and conflicting existing
Books values are reported without an update; fully linked payments are skipped.
It derives the inclusive lower date bound from the oldest `Payment_Date` in the
Creator `matched` report and requires a Books `--location-id`. The customer
payments list API has no documented date-range or location filters, so the
workflow applies both to the paginated response and verifies each scoped payment
against a detail read immediately before a live update. Books list rows expose
the `cf_creator_record_id` and `cf_creator_payment_id` values for a read-only
audit, and this organization returns them under the `customerpayments` list key.
It audits payments missing either Creator custom field,
cross-checks unmatched Books payments in Creator `All_Payments`, and reports
numeric `Payment_ID` gaps from `matched` with their presence or absence in
`All_Payments`. Multiple Creator records claiming one Books payment block writes.
Creator's `Customer_Name` lookup uses `zc_display_value` or `Name` for exact
fallback matching; `PaymentNo` and `Books_Transaction_Id` may be empty in the
matched report. The workflow takes native payment identifiers from the
canonical `All_Payments` row when that report supplies them. A supplied Creator
payment number that is absent from the scoped Books payments blocks fallback
matching to a different number. The CLI accepts `--checkpoint-path` for a
distinct audit file.
Live Books detail reads, updates, and verification reads are paced to remain
below Books' organization-level request limit. Code 44 pauses and retries; a
persistent limit aborts the run so later payments can be resumed safely.

The application never creates customer payments and never changes
bank-transaction matches. Dry-run is the default. Writes require `--execute`;
multi-record writes also require `--allow-batch`. An atomic JSON checkpoint
makes runs auditable and restartable. It is updated after every row, and a
successful update is read back from Books before being checkpointed. Duplicate
payment numbers, conflicting identifiers, missing payments, and ambiguous
matches are never written automatically.

# Online Payments Human Review

Withdrawal narrations containing `TNPDCL` (case-insensitive substring) propose
an Electricity expense, ahead of salary and TA rules. These lines are excluded
from customer matching and appear in Expenses with individual or bulk confirmation.
Posting resolves one active expense account named `Electricity` (case-insensitive);
missing or ambiguous accounts block posting. Refresh creates proposals only, and
posting revalidates the live bank line before categorization.

Generic `CHQ DEP - CTS CLG1` narration prefixes, including any clearing-location
suffix up to the first colon, are excluded from remitter tokens and customer
suggestions, ignoring case and spacing around separators. Actual customer text
after the colon remains eligible; bank date, amount, and cheque-reference
matching are unchanged.

Withdrawal narrations containing the exact token `POLY2300277498` (case-insensitive)
propose a **vendor advance** to **Polycab**, branch **Sri Bharath Electricals**.
This rule precedes salary and TA rules and excludes the line from customer matching.
The review table shows the vendor and branch and offers individual confirmation.
Posting revalidates the live bank line, resolves a unique active vendor named
Polycab or Polycab India Limited and the active branch by exact name, and uses
`categorize_as_vendor_payment` with `location_id` and no bill allocations.
Missing or ambiguous metadata blocks posting; refresh only creates proposals.

Case-insensitive whole-word narration rules reserve **CASH DEPOSIT** deposits
for cash-to-bank transfer proposals and **Salary** withdrawals for salary
expense proposals, excluding them from customer payment matching. Incoming
salary lines and outgoing cash-deposit lines do not qualify. Salary takes
precedence over a TA suffix. Refresh live data to classify existing queue rows.
Salary uses `PAYMENT_SALARY_EXPENSE_ACCOUNT_ID` (default `1094368000000000543`,
Salaries and Employee Wage); cash transfers use `PAYMENT_CASH_ACCOUNT_ID`
(default `1094368000005226023`, Cash-SBE). Both accounts are validated by direct
detail reads for active expense/cash type. Transfers use the reviewed line's
bank as destination and the Books `transfer_fund` categorization endpoint.
The Expenses view and expense multiselect include salary. Cash transfers have
their own dropdown view and individual confirmation. These rules propose
categories only; they do not post during refresh. Posting revalidates the live
line's classification, date, amount, narration, and reference.

## Internal bank transfers

**Bank Transfers** pairs uncategorized withdrawals and deposits across the configured
bank accounts. A pair requires the same parsed date, exact absolute amount and
non-empty reference (trimmed and case-insensitive). References reuse the existing
bank-specific reference resolver. Same-bank lines, unknown directions, missing
references and invalid/zero amounts do not qualify. Existing explicit cash,
expense and vendor narration rules retain priority. Multiple possible opposite
lines are shown as **Ambiguous** and cannot be posted. Both sides of candidate
pairs are excluded from Creator customer matching and Analytics customer hints.

The Bank source retains one row per statement line and shows source → destination,
date, amount, reference and both statement IDs. Either row's **Confirm bank transfer**
action confirms the same operation. There is no automatic posting during refresh.
The server rechecks both live lines, their reviewed values, mutual uniqueness,
active bank accounts and equal known currencies before posting.

The operation reuses one existing Books transfer offered for both lines when its
saved banks, date, amount and reference agree. Multiple existing matching transfers
block posting. Otherwise it creates one `transfer_fund` transaction, checkpoints
its ID and matches both statement lines to it. Each match is verified through the
transfer's `imported_transactions` detail before success. Both lines must be verified
before the operation is complete. No Creator record or customer payment is created.

`bank_transfers` in the existing atomic queue stores each operation's stage, native
transfer ID and error. Refresh preserves interrupted operations and reserves their
lines; a recovery row keeps **Resume bank transfer** available after the first line
has been matched. Retries reuse the saved native transfer. An interrupted create
uses a stable description marker to recover the transfer; an uncertain response
without unique evidence blocks another creation and requires Books review.
Cross-currency transfers are unsupported. Live bank transfer posting remains a
reviewer-confirmed action; implementation checks use mocked Books writes.

The production UI is named **Bank Statement Categorization**. It retains the
Creator online and cheque payment matching flow and adds other uncategorized
Books bank lines to a separate review table. Bank narrations are compared
with distinct customer names from Analytics Payment Customer Finder; complete
name matches are suggestions only. A withdrawal whose description ends in
`/TA` is proposed as Employee Travel Expense. A reviewer must explicitly
approve it, after which the workflow re-reads the uncategorized bank line,
checks its date, amount, and description, resolves one active expense account,
and calls Books' categorize-as-expense endpoint. The review app uses
`PAYMENT_TRAVEL_EXPENSE_ACCOUNT_ID` (default `1094368000029132050`), overridable
with `--travel-expense-account-id`. The workflow validates the selected ID's
active expense type through a direct account detail read, since the Books account
list can omit the selected account; without an ID it falls back to the exact account name. The
proposal state prevents a repeat click from posting twice.
In the production bank feed and Finder view, `debit` means deposit and
`credit` means withdrawal. The `/TA` expense proposal applies only to credit
lines.

The review interface uses three independent dropdowns: **Bank / Creator**,
**Expenses / Vendor Payments / Customer Payments / Cash Transfers / Bank Transfers**, and
**Ready for review / Ambiguous / No Match**. Defaults are Bank, Customer
Payments, and Ready for review. Creator supplies customer payments only;
other Creator categories show an explicit empty state. **Bank** uses the full
Books `Status.Uncategorized` statement snapshot, with one row per bank line.
Each customer line lists the pending Creator records matching its bank date,
amount, and reference rules, including date-and-amount reference mismatches.
Independent comparisons retain competing Creator records even if the posting
queue has reserved that line for one proposal. A single fully reviewable Creator
proposal is Ready for review; competing, reference-mismatched, or blocked
proposals are Ambiguous; no Creator match is No Match. Analytics customer hints
remain supplementary and do not turn a missing Creator match into a ready one.
Expense, vendor advance, and cash-transfer proposals are ready for category
review through their existing confirmed actions. **Creator** uses pending
payments whose `Books_Transaction_Id` is blank and compares each with bank
candidates. Missing candidates appear under No Match. Older saved queues lacking
the complete `bank_records` snapshot require a live refresh before Bank can show
its source; the UI explains this instead of reconstructing an incomplete feed.
Completed entries are excluded from these pending review queues.
Rows sort oldest-first by bank statement date for Bank and displayed Creator
payment/cheque date for Creator, across all matching states. Missing or invalid
dates appear last; equal dates retain source order.
Search and select-all apply to the visible source, category, and match status.
Changing a dropdown clears bulk selections. Expenses, vendor advances, and cash transfers provide row checkboxes,
select-all-visible, and sequential confirmed bulk categorization through one server batch. The batch
reads the uncategorized banks once, validates each row against that fresh snapshot,
and saves successful rows individually. Polycab vendor and branch metadata are
resolved once per batch and discarded on failure. The confirmation
lists each amount, bank, date, and proposed expense/vendor/transfer action; failed rows remain selected for retry. Individual confirmation and
fresh posting validation remain required.

`apps/payment_review.py` serves a loopback-only review queue for the
production Creator `Online_Payments` report. It maps `Payment_Amount`,
`Reference`, and the `Customer_Name` lookup to reconciliation values, resolving
the lookup through `All_Customers1.Customer_Id` before any Books payment is
proposed.

Only a unique date, amount, and reference match is eligible for acceptance.
The production review queue also validates the Creator customer name against
historical categorized records in Analytics `Payment Customer Finder` view
`264324000006111037` in workspace `264324000000002043`. The workflow extracts
remitter identifiers (UPI VPA, phone numbers, remitter names) from the bank line
narration and executes targeted SQL queries against the Finder view rather than
downloading the full table. If historical records identify exactly one customer, that customer must confirm
the Creator customer name; a unique different customer produces a visible conflict warning. The proposal
retains its invoice preview and can be accepted individually after explicitly
confirming that the payment belongs to the Creator customer. The server requires
`allow_customer_name_override=True`, rechecks live history before posting, and
records the confirmed customer, historical names, and confirmation time in the
local checkpoint. Bulk acceptance does not override customer conflicts; use
individual Accept & Push. History matching multiple distinct customers is inconclusive: the UI
shows a note and the candidate remains eligible for invoice preview and acceptance
subject to the other matching and allocation checks. If no prior records exist for that
remitter, the exact date, amount, and reference match remains reviewable.
Redacted UPI local IDs such as `XXuram@okaxis` search history using the
visible four-character suffix plus handle (`uram@okaxis`), including older
unredacted narrations. The suffix alone is never a remitter token. Redacted IDs can collide; multiple historical customers therefore produce the
same non-blocking note, while a unique different customer requires individual customer confirmation.
Date, amount, and reference predicates remain unchanged.
A targeted lookup is also re-executed immediately before a push so a stale preview
cannot authorize a payment.
The review app uses the separate Analytics organization ID from
`ANALYTICS_ORG_ID`; its default corresponds to the configured Finder view.
The Bank source puts bank columns first; Creator puts Creator columns first.
Both retain proposed bank and Creator values side by side.
The browser UI presents Creator and bank values side by side. Rejection changes
only the atomic local state file. `Accept & Push` revalidates that the bank line
is still uncategorized and refreshes the customer's open Books invoices. The
payment is allocated oldest-due-first before Books creation, then its ID is
checkpointed, the bank line is matched, and the ID is written into Creator's
`Books_Transaction_Id`. Repeated acceptance of a fully pushed entry is
idempotent. Entries without a unique match cannot be accepted. Payment creation requires
a fresh open-invoice allocation, preventing the entire amount from becoming unused credit.

The review row shows the proposed invoice numbers, due dates, balances, and
amounts applied. Invoice previews load through the row’s **Load invoice preview** action rather than
during refresh. Acceptance always queries invoices again so it uses current Books
balances. `lazy_invoice_previews=False` retains eager previews for SDK callers,
with one invoice query per customer per refresh. Allocation may span multiple invoices. When their total balance is
less than the payment, Books receives all possible allocations and only the
displayed excess remains unused credit.

Ambiguous matches retain every competing bank line in the local queue. The UI
provides a dedicated `Ambiguous` filter and shows each candidate's bank, date,
amount, reference, and narration for inspection. These entries remain
non-reviewable for pushing until matching becomes unique, so viewing ambiguity
does not weaken the workflow's mutation safety.
When configured, the Analytics Payment Customer Finder view adds customer-name
suggestions to each ambiguous bank candidate using its transaction number where
available, plus date, amount, and reference. Suggestions are informational and
do not select a bank line automatically.

When date and amount agree but the reference predicate fails, the queue retains
the bank lines under the `Ambiguous` match status. This exposes likely
reference-data problems for human review. A reviewer can explicitly select one
candidate and confirm the reference override. Immediately before posting, the
workflow verifies that the selected line remains uncategorized in the same bank
account and still matches the configured date and amount tolerances. The
selection then follows the normal invoice-allocation, payment-creation, bank
matching, and Creator-checkpoint sequence. Fully matching ambiguous entries
remain non-pushable.

The HTTP server binds only to a loopback address and mutation requests require
both an explicit confirmation body and a random per-process review token. The
queue state is stored at
`output/collection_reconciliation/online_payments_review.json` by default.
Pass `--refresh-only` to rebuild that production review state and print its
entry counts without starting the HTTP server or writing to Zoho. This CLI
option remains available without a separate project dashboard entry.
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
Creator report requests apply server-side null/empty criteria; the local blank
check remains defensive. Cheque details are skipped when no pending cheques exist.
Only source records whose configured Books transaction ID field (normally
`Books_Transaction_Id`) is missing, null or blank are proposed. The default
**Pending Creator payments** view retains every pending record, including records
without a bank candidate, displayed as **Not available**. Multiple matches and
reference-mismatch candidates remain visible for review. Completed local checkpoints remain in the saved queue and are excluded from
the three pending match-status views.
The two source reports, cheque-detail report, customer lookup report, and
canonical checkpoint report are selected through the
grouped `PAYMENT_CREATOR_REPORTS` runtime configuration, whose defaults retain
these production link names.
Online rows use `Payment_Date` and Books mode `banktransfer`; cheque rows use
`All_Cheque_Details.Presented_Date` when available and Books mode `check`.
Presentation is optional: a missing detail or blank presented date falls back
to `Cheque_Date`, labelled in the UI. Multiple matching detail rows still block
matching, and a missing or invalid date remains non-reviewable. The existing
seven-day clearing window applies; when using the cheque date, bank dates before
that date are excluded in both preview and pre-post validation. For cheques, the selected bank date is the Books payment date and the
Presented_Date checkpoint; the original cheque date remains the matching anchor
when presentation is absent. After bank matching, the approved push reuses or
creates a Cheque_Details record linked by Payment_ID, saves the bank date, and
reads it back before completing the All_Payments checkpoint. Cheque-detail
checkpoint reads request `field_config="all"`, including cursor pages, because
the default report omits the Payment_ID lookup needed for identity verification. Retries reuse the
existing detail and Books payment; duplicate details and cheque-number conflicts
block the checkpoint. Preview refresh never writes a presentation record.

Each entry retains its source report so the final
`Books_Transaction_Id` checkpoint is written through the correct Creator
record via the canonical `All_Payments` report. The workflow validates the
Creator response and reads the record back with all fields before marking the
queue entry pushed. The checkpoint writes both the Books payment ID to
`Books_Transaction_Id` and the human-readable Books payment number to the
Creator `PaymentNo` (`Payment#`) field. A failed Creator checkpoint retains the completed
`bank_matched` stage, so retry reuses the existing Books payment and only
retries the Creator write. The UI shows the payment type separately from the bank name. Online
matching remains same-day by default. Cheque matching allows a seven-day bank
clearing window from the presented date or fallback cheque date while requiring an exact amount and a
match on the final four digits of the cheque number. The final-four comparison
examines each numeric run in the bank reference and narration, so clearing-date
digits cannot hide the cheque number.

Books can identify a single-invoice customer payment in the bank-match candidate
response by its invoice-application ID rather than by the parent customer-payment
ID. The review workflow verifies that application ID by reading the checkpointed
parent payment, submits the candidate ID returned by Books for matching, and
continues to store the parent payment ID in Creator. A retry reuses the existing
parent payment and never creates a duplicate.

`apps/backfill_online_payment_creator_fields.py` discovers additional
Creator `Online_Payments` records that already have a corresponding Books
customer payment. It only accepts a unique exact customer-ID, date, amount, and
reference match (or a consistent existing Books identifier), then can write
`Books_Transaction_Id` and `PaymentNo`. Missing, incomplete, and ambiguous
records are reported without mutation. Dry-run is the default. Live batch
writes require `--allow-batch`; each Creator response and readback is verified,
and an atomic per-row checkpoint supports safe resumption.

The long-running review server supplies Books and Creator token-refresh
callbacks backed by the configured HTTP token broker. A 401 response refreshes
the affected service token and retries the request once. Authorization failure
during the pre-push bank snapshot creates no payment; an individually attempted
entry is left retryable with no Books checkpoint.

Legacy queue payments created before invoice allocation can be repaired with
`apps/repair_review_payment_allocations.py`. Dry-run is the default. Execute
mode updates the existing Books payment rather than replacing it, preserves any
existing invoice applications, allocates only the live `unused_amount`
oldest-due-first, and reads the payment back after every update. An atomic JSON
checkpoint records planned, repaired, already-allocated, no-open-invoice, and
incomplete-checkpoint outcomes so the operation is safely repeatable. A failed
Books update aborts the run without recording a successful repair.

# Request Efficiency

Refresh overlaps Creator payment reads with Books bank reads using two workers.
Each client is used sequentially, and request-metric context is propagated into
the workers. Bank candidates are indexed once by parsed date and absolute amount;
lookup retains source order, date/amount tolerances, competing claims and cheque
clearing rules. A reverse candidate map also avoids rescanning all Creator
comparisons for each displayed bank row.

The review server retains session-local Analytics token results and Creator
customer mappings for 300 seconds by default. Empty historical matches are
cached too. Caches are scoped to their injected client and configured
workspace/view or app/report; they are never written to the state file.
Bank statements are read on every refresh; invoice balances load on demand by default. A customer
conflict can load its invoice preview for review, and repeat acceptance of an already pushed
entry returns before making network calls.

`refresh(force_refresh=True)`, the UI **Force refresh** button, and CLI
`--force-refresh` bypass all session caches. The CLI exposes
`--analytics-preview-ttl`, `--customer-mapping-ttl`, and `--travel-account-ttl`
in seconds; zero disables the corresponding cache. Payment acceptance always
performs fresh Analytics validation and reads live invoice balances before
creation, regardless of preview caching. TA account resolution is cached for
300 seconds and invalidated when categorization raises or is rejected; the bank
line is still revalidated for each categorization. No write is automatically
retried after an account rejection.

A successful empty targeted SQL result no longer triggers a full Finder export.
The fallback remains available when targeted queries fail or are unavailable.
SQL batches obey both `--analytics-batch-tokens` (default 35) and
`--analytics-max-sql-bytes` (default 6000, measured in UTF-8 before URL encoding).
These are application budgets, not verified Zoho maxima; an individually
oversized token fails before querying. The [Zoho SQL export documentation](https://www.zoho.com/analytics/api/v2/bulk-api/export-data-async/create-export/sql-query.html)
does not specify a maximum SQL length, so a larger token batch is opt-in.

The app logs payload-free completed SDK request counts by service for refresh,
acceptance, bulk acceptance, and TA categorization using the existing transport
callback. Preview cache-hit counts are logged separately and included in the
saved batch. Completed SDK counts include export creation, polls, and downloads,
but exclude token-broker calls, transport exceptions, and internal HTTP retries
because the callback fires once after retry handling. These counts are not
Zoho API-unit usage. Organization-wide invoice fetching remains deferred until
its page count can be compared with customer-specific fetching on production
volume; changing the fetch strategy without that measurement could add reads.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), [Zoho Books Client](zoho-books.md), and [Development Runbook](development-runbook.md).
