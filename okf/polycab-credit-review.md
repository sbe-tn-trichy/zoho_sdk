---
type: Workflow
description: Poppler PDF evidence and reviewed RMA vendor-credit, journal and customer-payment corrections.
---

# Polycab vendor-credit review

`workflows.polycab_credit_review.review_polycab_vendor_credits()` receives a Books
client, `RmaCreditPolicy`, inclusive dates and optional exact credit numbers. It
downloads every detail-record attachment, extracts all pages with Poppler
`pdftotext -layout`, reads linked journal/payment details and returns typed
`CreditAudit` records. List attachment flags are not authoritative. Filenames
are audited for duplication; this workflow does not delete attachments.

Books filters are enforced locally. Missing selections, ambiguous credit numbers
and mismatched detail identity stop the review. Read errors, unsupported PDFs,
conflicting copies, missing attachments and amount/date mismatches block writes.
Duplicate copies of the same supplier note are counted once; distinct notes are
combined, with supplier debit notes subtracted. Blank adjacent PDF fields are
never interpreted as RSO/customer-invoice values.

## Accounting policy

`RmaCreditPolicy` requires explicit vendor, customer, RMA item, RMA expense and
Vendor To Customer clearing account IDs. Catalog reads are unnecessary when
these reviewed IDs are supplied; any future catalog resolution must use Inventory
and purchase-account scoping. No account, customer or item is inferred by name.

The supported correction shape is an untaxed, undiscounted credit with one or
more quantity-one return lines corresponding to individual PDFs, one RSO and one
explicit customer invoice. Against Invoice is set to true using its existing
custom-field ID. Unrelated custom fields, native numbers, dates, locations,
amounts, attachments and applied vendor bills are preserved.

The journal must already exist, be published, contain one debit and one credit
for the full credit amount, and credit the configured clearing account. The
workflow changes only its matching expense debit to the RMA expense account.
The existing customer payment must belong to the configured customer and
clearing account and reconcile to its allocations plus unapplied amount.

References use exact token matches. Ambiguous references block corrections.
Unique amount/date candidates are explicitly inferred and cannot be corrected
without a reviewed explicit journal/payment ID. These overrides do not bypass
identity, amount, location, date or accounting checks. PDFs naming supplier bills
instead of customer invoices remain blocked for manual mapping.

Rounding differences within the policy tolerance (default INR 1.00) are reported
and documented. Original allocations, including small amounts applied to another
invoice or left unused, are retained. The workflow never increases invoice
totals, reallocates payments or creates missing journals/payments.

## Reference format and modules

Each reference occupies a labeled line (`RSO#:`, `INV#:`, `JNL#:`, `CP#:`).
Repeated `CN#:` and `SUPPLIER_CN#:` lines represent combined supplier notes.
Rounding invoice, amount applied and unused amount have separate labeled lines.
VC line descriptions, VC notes, journal lines/notes and payment descriptions use
the same format. Existing human notes are preserved; repeated runs replace
managed labeled lines without appending duplicate reference blocks.

- `pdf.py` owns Poppler extraction and supplier-note parsing/deduplication.
- `evidence.py` owns scoped Books reads and reference linkage.
- `rules.py` owns domain accounting checks and eligibility.
- `correction.py` owns supported payloads, preflight and read-back verification.
- `workflow.py` only coordinates reads, extraction, linkage and rule evaluation.
- Generic streaming downloads and labeled reference formatting/parsing live in
  `zoho.helpers.files` and `zoho.helpers.references` and are publicly exported.
  Currency/date conversions and atomic checkpoints reuse `workflows.core`.

## CLI and execution

Configure `POLYCAB_VENDOR_ID`, `RSO_CUSTOMER_ID`, `POLYCAB_RMA_ITEM_ID`,
`POLYCAB_RMA_ACCOUNT_ID` and `POLYCAB_CLEARING_ACCOUNT_ID` through the existing
configuration loader, or provide the corresponding CLI ID flags. Poppler must
be installed and `pdftotext` available on PATH; image-only PDFs require manual
review. No OCR or filename-based amount/identity fallback is used.

```sh
.venv/bin/python apps/review_polycab_vendor_credits.py --fy 25-26
.venv/bin/python apps/review_polycab_vendor_credits.py --fy 25-26 --credit "$VC_NUMBER"
.venv/bin/python apps/review_polycab_vendor_credits.py --fy 25-26 --credit "$VC_NUMBER" --apply
```

The default is read-only audit and correction preview. `--apply` requires
explicit `--credit` selections (repeat the flag for multiple credits). If any
selected credit is ineligible, no selected updates are submitted. Use
`--journal-id` and/or `--payment-id` only with one credit after reviewing the link.

Run-specific reports contain findings, before-state and proposed payloads.
Live execution requires an atomic checkpoint callback, preflights all three
records and every invoice allocation, rechecks immediately before each write,
then verifies saved payloads and financial invariants. Already-correct payloads
are not resubmitted. Checkpoints record pending intent before API submission and
completed verified operations after each read-back.

The three writes and multi-credit runs are sequential, not atomic. An API or
verification failure stops execution and reports completed/pending operations;
there is no automatic rollback, blind retry or automatic resume. Review live
state and the checkpoint before planning recovery. Concurrent writers can still
race the preflight checks. Later edits may invalidate saved audit evidence.

Artifacts default to ignored `output/polycab_credit_review/`; explicit absolute
output directories are supported. Do not commit reports or downloaded PDFs.
The CLI constructs clients through `workflows.core.auth`. Public APIs and result
types are exported from the domain package and the workflow root.

Related: [Books](zoho-books.md), [architecture](architecture.md),
[workflow helpers](workflow-helpers.md), [vendor/customer offset](vendor-customer-offset.md).
