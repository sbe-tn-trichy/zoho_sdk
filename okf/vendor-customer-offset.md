---
type: Workflow
description: GSTIN-safe clearing of linked customer receivables and vendor payables through paired payments.
---

# Vendor-Customer Offset

`workflows.vendor_customer_offset.run_vendor_customer_offset()` offsets balances
for contacts that exist once as a customer and once as a vendor under the same
valid GSTIN. A GSTIN is skipped when either contact type occurs more than once.

The offset amount is the lower of the customer's outstanding receivable and the
vendor's outstanding payable. The workflow allocates the amount oldest-due-first
to open invoices and bills, and skips a pair rather than creating unapplied
credit when the open documents cannot absorb the complete amount.

The workflow creates one payment pair per participating vendor bill: one
customer payment and one vendor payment for the same amount and the bill's own
invoice date. When the available customer receivable is lower than total vendor
payables, the last participating bill is partially settled. Customer invoice
allocations carry forward across payment pairs without reusing an allocation.
A pair is skipped if a participating vendor bill has no valid date.
Generated references include the vendor bill ID and are capped at the live
Books limit of 50 characters.

Only documents with positive balances in payable/payment-eligible states are
allocated. Void, draft, paid, rejected, and approval-state invoices and bills
are excluded even if the list response retains a historical balance.

Both payments use the `Vendor To Customer` bank account by default. Customer
payments use `account_id`; vendor payments use `paid_through_account_id`.
Account ID can be supplied explicitly to avoid name lookup.
An optional `vendor_id` limits preview and posting to exactly one vendor.

Dry-run is enabled by default and does not verify or create the contact link.
During a live run, `ensure_linked=True` uses the Books web-client operation
`POST /customers/{customer_id}/link`; the Zoho `3051` response is treated as an
idempotent indication that the contacts are already linked.

The customer payment is created first. If vendor-payment creation fails, the
workflow attempts to delete the newly created customer payment and reports the
rollback outcome. Callers must inspect the `failed` collection, especially any
rollback marked `failed`, before retrying.
