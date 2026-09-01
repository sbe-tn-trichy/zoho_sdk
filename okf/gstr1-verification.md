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
report from Zoho Books invoices, credit notes, and e-invoice records. With no
month argument it selects the previous calendar month; callers can pass an
explicit `YYYY-MM` or an `as_of` date for deterministic scheduling and tests.

## Checks

Before applying checks, the workflow reads Books locations and groups them by
`tax_settings_id`, the tax-registration identifier assigned to each India
location. Every check runs independently for each GST registration and its
results are exposed under `gst_registrations`. If location metadata cannot be
loaded, documents remain isolated by individual `location_id`, the report is
marked incomplete, and locations are never combined speculatively.

- Draft invoices and credit notes are reported together with identifiers,
  dates, customer names, totals, and statuses. Void documents are retained in a
  separate explanatory list.
- Invoice and credit-note number sequences are checked independently by prefix.
  Missing numbers, duplicates, date reversals, unparsable numbers, invalid
  dates, and inconsistent numeric widths fail verification. Void documents do
  not participate in chronology or other sequence violations, but their
  numbers remain occupied so they are not incorrectly reported as gaps.
- Sequence analysis loads the complete configured financial year, by default
  April through March, while reporting only groups and violations that touch
  the selected month. This prevents a backdated number outside the month from
  being incorrectly classified as missing.
- When e-invoicing is applicable, the workflow reads the nested
  `einvoice_details` object already returned on each invoice and credit note.
  Applicable active documents pass only when their status is pushed or
  manually pushed and `inv_ref_num` contains the IRN. Not-pushed,
  pending, failed, cancelled, unknown, and pushed-without-registration-evidence
  records are exceptions.

Active monthly documents without an `einvoice_details` object are exposed as
`not_applicable_or_not_returned`; they do not fail the check because Zoho marks
e-invoice applicability by including that object. Set
`GSTR1VerificationConfig(e_invoice_applicable=False)` when e-invoicing is not
enabled for the organisation.

## Safety and completeness

The workflow calls only location, invoice, and credit-note list operations. It
never pushes, cancels, or updates a transaction. Any location, monthly, or
sequence-scope API failure is recorded under `fetch_errors`, sets `complete` to
false, and prevents `overall_passed` from becoming true.

## Related concepts

See [Zoho Books Client](zoho-books.md), [Package Architecture](architecture.md),
and [Development Runbook](development-runbook.md).
