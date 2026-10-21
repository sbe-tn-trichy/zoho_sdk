---
type: Workflow
description: Supplier Scheme credits and checkpointed RSO vendor-credit, journal and customer-payment creation.
---

# Polycab credit import

`apps/import_polycab_credit.py` is the primary single-PDF import entry point.
It previews by default; `--apply` authorizes financial writes. Configure or pass
explicit vendor, location, scheme item, scheme account, RMA expense and clearing
account IDs. The RSO item defaults to the reviewed RSO CN identifier. Inventory
is the source for item inspection; vendor catalog searches require purchase-account
scoping. The API is exported by `workflows.polycab_credit_memos` as
`CreditImportPolicy` and `import_credit_pdf`.

Supplier PDFs are parsed by the strict Poppler parser shared with
[credit review](polycab-credit-review.md). Scheme CN lines use Polycab Kitty.
Return credits require both an RSO number and an explicit customer invoice number.
A supplier bill reference is never substituted for the customer invoice.

RSO import creates a quantity-one vendor credit using RSO CN and RMA Expense,
then a published journal debiting RMA Expense and crediting the Vendor To Customer
bank, then a customer payment into that bank allocated only to the exact PDF
invoice. All records use the PDF date and credit amount. The invoice must match
uniquely, belong to the selected location, be issued and have sufficient balance.
The invoice customer owns the payment. Any small remaining balance is retained;
there is no rounding write-off or payment reallocation.

Vendor credit line descriptions, journal line descriptions, and customer payment
descriptions share labeled supplier CN, RSO, invoice, VC,
journal and payment references. Native IDs are included for direct lookup.
Final references are written back after all native numbers are known. Transaction
notes are left unchanged; reference blocks are not appended to notes. The source
PDF is attached to the vendor credit. Every submitted record is read back and
checked; mismatches stop the run.

Existing vendor credit numbers stop creation. An atomic checkpoint records pending
intent before each write and returned IDs immediately after creation. A failure
records completed records and the uncertain operation. Reusing any existing
checkpoint is blocked: review live state before recovery, with no automatic retry,
resume or rollback. Operations across the three records are not atomic and
concurrent external writers remain a limitation. Checkpoints default to ignored
`output/polycab_credit_import/`; select a distinct `--checkpoint` per source PDF.

The older `create_vendor_credit_from_pdf` and batch processor retain scheme-only
compatibility, now defaulting to Polycab Kitty with exact account-name matching
and no Purchase Discounts fallback. RSO creation through the older function is
rejected with guidance to the complete importer. The review workflow remains
responsible for correcting records that already exist; it does not create missing
journals or payments.
