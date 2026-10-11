---
type: Workflow
title: GSTR-1 Verification
description: Read-only previous-month invoice, credit-note, sequence, draft, and e-invoice readiness checks.
tags: [gstr-1, gst, invoices, credit-notes, e-invoice, compliance]
sources:
  - id: workflow-source
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/gstr1_verification/verifier.py
    title: GSTR-1 verification workflow
    author: team:sbe-tn-trichy
    last_modified: 2026-08-10
status: active
---

# GSTR-1 Verification

`workflows.gstr1_verification.verify_gstr1()` builds a read-only readiness
report from the Zoho Analytics synced Books tables by default. Pass an
`analytics_client` and optionally `analytics_workspace_id` (default
`264324000000002043`). Set `force_refresh=True` and supply a `books_client`
to fetch live Books invoices, credit notes, and locations instead. The report's
`data_source` identifies the selected API; Analytics errors never trigger an
automatic Books fallback. With no
month argument it selects the previous calendar month; callers can pass an
explicit `YYYY-MM` or an `as_of` date for deterministic scheduling and tests.

## Checks

Before applying checks, the workflow reads locations from the selected source and groups them
by their GSTIN (`tax_reg_no`), falling back to `tax_settings_id` when GSTIN is
not returned. Every check runs independently for each GST registration and its
results are exposed under `gst_registrations`. Each registration also contains
`location_reports`, including fetched locations with no documents in the target
month, so the report can be reviewed GSTIN-wise and then location-wise. If
location metadata cannot be loaded, documents remain isolated by individual
`location_id`, the report is marked incomplete, and locations are never combined
speculatively.

- Draft invoices and credit notes are reported together with identifiers,
  dates, customer names, totals, and statuses. Void documents are retained in a
  separate explanatory list.
- Credit-note HSN validation is enabled by default. Analytics exports the
  transaction `HSN/SAC` values from `Credit Note Items (Zoho Books)` and
  `Invoice Items (Zoho Books)`, joined to document headers and customer names.
  Each active monthly credit-note line must have an exact normalized HSN match
  on a non-draft, non-void invoice under the same seller GSTIN, dated on or
  before the credit note. B2B credits require the same Customer ID and include
  all available earlier history. B2C credits reduce pooled sales: an invoice
  for any customer qualifies within the preceding six calendar months, inclusive
  of the credit date and the date six months earlier (clamped at month end).
  Both rules allow other locations within that GSTIN. Invoice exports combine
  customer history with all recent sales needed for the B2C window.
  Transaction `GST Treatment` takes precedence over the customer's current
  treatment; the customer treatment is used only when the transaction field
  is absent. Consumer and Unregistered Business use B2C; registered regular
  and composition businesses use B2B. Missing or unsupported treatment makes
  the line unverifiable. Numeric export suffixes such as `.0` are removed; different
  HSN lengths do not implicitly match.
  Bulk exports allow up to 60 polling attempts to accommodate queued jobs.
  Mismatches appear under `checks.credit_note_hsn.violations` with credit-note,
  customer, line and HSN evidence, the selected B2B/B2C rule and eligible
  invoice HSNs. Successful lines appear under `matched` with one qualifying
  invoice's number, date and customer, including in the Markdown report.
  These are violations of the workflow validation rule, not a determination
  of statutory liability. [CGST Section 34](https://taxinformation.cbic.gov.in/content-page/explore-act/1000304/1000001)
  ties credit notes to supplies; the customer-HSN comparison is an audit check.
  Missing codes, identity, registration, lines or unsynced credit notes are
  `unverifiable`, make the report incomplete and prevent a pass. All aggregate,
  GSTIN and location results include this check. Domain callers may explicitly
  disable it with `GSTR1VerificationConfig(validate_credit_note_hsn=False)`.
  Explicitly confirmed financial credit notes can be supplied as a tuple of
  IDs in `financial_credit_note_ids`; the CLI reads these from the local
  `GSTR1_FINANCIAL_CREDIT_NOTES` mapping. They are excluded from HSN and
  e-invoice checks as GST not applicable and listed separately under
  `financial_credit_notes` in the HSN result and Markdown report. They retain
  draft and sequence checks. Missing HSNs or zero-tax values alone do not
  classify a document as financial; confirmation is required to avoid hiding
  incomplete evidence on other GST credits.
- Invoice and credit-note number sequences are checked independently by prefix.
  Missing numbers, duplicates, date reversals, unparsable numbers, invalid
  dates, and inconsistent numeric widths fail verification. Void documents do
  not participate in chronology or other sequence violations, but their
  numbers remain occupied so they are not incorrectly reported as gaps.
- Sequence analysis loads the complete configured financial year, by default
  April through March, while reporting only groups and violations that touch
  the selected month. This prevents a backdated number outside the month from
  being incorrectly classified as missing.
- When e-invoicing is applicable, the Books path reads the nested
  `einvoice_details` object already returned on each invoice and credit note.
  Applicable active documents pass only when their status is pushed or
  manually pushed and `inv_ref_num` contains the IRN. Not-pushed,
  pending, failed, cancelled, unknown, and pushed-without-registration-evidence
  records are exceptions.

On the Books path, active monthly documents without an `einvoice_details` object are exposed as
`not_applicable_or_not_returned`; they do not fail the check because Zoho marks
e-invoice applicability by including that object. Set
`GSTR1VerificationConfig(e_invoice_applicable=False)` when e-invoicing is not
enabled for the organisation.

## Safety and completeness

Analytics reads `Locations (Zoho Books)`, `Invoices (Zoho Books)`, and
`Credit Notes (Zoho Books)` through read-only SQL exports. Documents are fetched
using the synced Books column names, including `CreditNotes ID`,
`e-Invoice Status.`, and `e-Invoice Reference Number.` for registration evidence,
once per financial year and filtered locally for the target month. Missing
Analytics e-invoice evidence is classified as unknown and fails the applicable
check, unless an explicit `Not Applicable` status is exported or the caller
disables e-invoicing. Analytics data reflects its last synchronization; use
force refresh for current Books evidence. Missing required document fields or
invalid dates mark the report incomplete.

Run `apps/verify_gstr1.py --month YYYY-MM`; add `--force-refresh` for Books.
The CLI writes `output/gstr1_verification.md` by default and exits with status
1 if verification fails or is incomplete. It constructs API clients through
the workflow authentication factories. Force refresh obtains
document headers and existing readiness checks from Books; HSN evidence always
comes from Analytics, so both clients are constructed for that mode. Domain
callers using force refresh must supply an Analytics client when active credit
notes need validation; missing or conflicting synced evidence fails closed.

`--output` selects the Markdown report path; `--json-output` optionally saves
the structured result separately. The public `render_markdown_report()`
function renders results with source, period, completeness, GSTIN checks,
location summaries, and detailed draft, sequence, e-invoice and void evidence.
Pass `gstin_aliases` for short firm labels; the CLI uses `Config.GSTIN_ALIASES`.
Fetch failures mark registration results incomplete even when individual checks
pass. The renderer also accepts a saved single-registration report with period,
source, and completeness metadata.

The Books path calls location, invoice, and credit-note list operations, plus
read-only document detail operations when tax fields are absent from lists.
The HSN check adds read-only Analytics SQL exports. The workflow
never pushes, cancels, or updates a transaction. Any location, monthly, or
sequence-scope API failure is recorded under `fetch_errors`, sets `complete` to
false, and prevents `overall_passed` from becoming true.

## Related concepts

See [Zoho Books Client](zoho-books.md), [Package Architecture](architecture.md),
and [Development Runbook](development-runbook.md).

## Financial amounts and Markdown

Reports expose `financial_summary` at the overall, GST registration, and
location levels, with separate `invoices`, `credit_notes`, and `net` amounts.
The fields are `total_taxable`, `igst`, `cgst`, `sgst`, and `total` (INR).
Credit notes are deducted from invoices; draft and void documents are excluded.
Document records expose `gst_amounts`. Decimal arithmetic avoids accumulation
errors; document totals retain Books rounding and adjustments.

Taxable amounts come from Books `total_taxable_amount`, and GST components
come from document `taxes`, reconciled to `tax_total`. Missing, invalid, or
unsupported tax components create fetch errors and incomplete summaries,
rather than silently substituting zero. Incomplete totals are partial.
`render_markdown_report(report)` renders checks and financial tables by GSTIN
and location. Detail fetching increases read-only API calls for active monthly
documents whose list responses lack tax fields.

Financial amount retrieval applies to Books force refresh. Analytics readiness
checks remain independent of Books; Analytics financial summaries are marked
incomplete when exported documents lack GST amounts. Use force refresh for
financial totals.
