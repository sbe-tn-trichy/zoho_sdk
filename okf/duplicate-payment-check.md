---
type: Concept
title: Duplicate Customer Payment Check
description: Read-only detection of exact duplicate customer payments in Zoho Books.
tags: [books, customer-payments, duplicates, audit]
status: active
---

# Duplicate Customer Payment Check

`workflows.duplicate_payment_check` reads every Zoho Books customer-payment page
and groups payments by the exact combination of customer ID, payment date, and
amount. Only groups containing at least two payments are reported. Customer IDs,
not display names, define customer identity so separate contacts with the same
name are not merged.

The live regional Books response returns the payment list under
`customerpayments` (without an underscore), so the workflow uses the SDK
resource's endpoint-derived pagination key.

The workflow is read-only and requires `ZohoBooks.customerpayments.READ`. When a
list item does not contain its customer ID, the checker retrieves that payment's
detail before evaluating it. Missing or invalid records are returned in the
`skipped` collection rather than silently matched.

Use `scripts/check_duplicate_customer_payments.py` to run the check through the
configured token broker. Optional customer and inclusive local date filters are
available. The Markdown report defaults to
`output/duplicate_customer_payments.md` and groups each duplicate set under its
customer name and payment date, followed by reference-and-amount bullets. An
interactive HTML table remains available by passing an `.html` output path.

# Related Knowledge

See [Zoho Books Client](zoho-books.md), [Package Architecture](architecture.md),
and [Configuration Reference](configuration.md).
