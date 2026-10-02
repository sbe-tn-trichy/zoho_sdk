---
type: Concept
description: Read-only customer invoice discounts and payment-allocation verification.
---

# Customer Invoice and Payment Review

`apps/review_customer_invoices_payments.py --customer-id <Books customer ID>`
exports all invoice statuses and dates for one customer to
`output/customer_invoice_payment_review/`. No Zoho records are changed.

The invoice CSV has Date (invoice date), Invoice Number, Invoice Value (final
total including tax and discount), CD Applied, and Payment. CD uses the native
invoice percentage when present; flat discounts become an effective percentage
of the discount base, rounded to two decimals. Missing discounts output 0.
This is the invoice discount, not payment discounts or credit notes.

Payment sums Books customer-payment allocations to that invoice, excluding
credits and write-offs. The accompanying payment CSV shows payment dates,
numbers, each allocation, and unused amounts. Payment totals and unused amounts
repeat per allocation and must not be summed across those repeated rows.
A JSON summary flags differences from invoice payment_made and differences
between payment totals and allocations plus unused amounts (refunds or
withholding may explain those differences). Detail reads validate customer and
record identity and are paced at half-second intervals. API failures abort
before artifact generation; malformed amounts never silently become zero.

The workflow public API is `review_customer_invoices_payments`, returning
`CustomerInvoicePaymentReview` with typed invoice and allocation rows.
