---
type: workflow
description: Review opposite postings in a Books account that span locations and audit payment-to-document location consistency.
---

# Inter-location Contra Review

Run `uv run python apps/review_inter_location_contra.py` to produce
`output/inter_location_contra_review.json`. The default account is the
`Vendor To Customer` clearing bank account, ID `1094368000002033114`. The
workflow checks FY 2025–26 and FY 2026–27 and includes the transaction date,
type, ID, debit or credit, amount, reference, description, and source location.

The workflow pages through the account-scoped Bank Transactions list, which
returns posting date, amount, direction, reference, and location for each entry.
The chart-of-accounts transaction endpoint returns a `transaction_list` of type
counts in this organization, even with a transaction-type filter. If Books
returns an incomplete page, the run fails instead of reporting a false clean
account.

## Location Verification Rules

### 1. Vendor To Customer Clearing Account (Contra Pairs)
For debugging and auditing offset pairs between customer and vendor:
- Opposite postings with a unique date and amount are paired. Equal references
  or a reference embedded in a composite reference strengthen the match. A
  pair with a missing reference stays review-only. Same-location pairs remain
  in the audit report but do not appear in the move queue.
- **All 4 locations MUST be identical**:
  1. **Bill Location** (from participating vendor bills)
  2. **Vendor Payment (Payment Made) Location**
  3. **Invoice Location** (from participating customer invoices)
  4. **Customer Payment (Payment Received) Location**
- If any of the 4 locations differs, the group is flagged with `four_way_location_consistent: false` and the distinct location set.
- The workflow proposes moving the customer payment only when every allocated document agrees with the vendor payment's location. Disagreeing documents require manual review. The workflow does not mutate Books data.

### 2. Standard Bank Accounts
When auditing standard bank accounts (e.g. `--mode bank`):
- **Vendor Payments (`vendor_payment` / Payment Made)**: Verifies that `vendor_payment.location_id == bill.location_id` across all allocated bills.
- **Customer Payments (`customer_payment` / Payment Received)**: Verifies that `customer_payment.location_id == invoice.location_id` across all allocated invoices.
- Any payment where the location differs from its underlying allocated documents is flagged with the payment number, recorded location, and document locations.

`--analytics` additionally matches payment numbers and invoice numbers against
the configured Zoho Analytics `CustomerPaymentLocationDiff` view. Its synced
data provides corroboration; source documents in Books remain authoritative.
Zoho Books has distinct update contracts for journals, payments, and bank
transactions, so a reviewed move must use the appropriate source document API
and verify both sides afterward.

`uv run python apps/create_inter_location_contra_query_table.py` validates a
live Analytics query over synced customer payments, vendor payments, journal
items, journals, and locations. `--apply` saves it as the `Inter Location
Contra FY25-27` Query Table. It is scoped to the clearing account and the two
financial years and contains contra pairs with different locations. Blank
reference matches are labeled `Verify pairing`. Analytics Query Table creation
requires `ZohoAnalytics.modeling.create`; it depends on the source table sync.
The Query Table also includes customer payments whose location differs from an
allocated invoice and vendor payments whose location differs from an allocated
bill across all synced Books bank accounts, within the same financial years.
Contra pairing remains scoped to the clearing account. `Bank Account ID` and
`Bank Account Name` identify the source account, and `Issue Type`
distinguishes these allocation mismatches from contra pairs. For allocation
rows, the debit side is the payment and the credit side is its invoice or bill;
`Amount` is the total payment amount. The Query Table joins each customer
payment to its allocated invoices and each vendor payment to its allocated
bills, taking location from the invoice and bill records themselves. Contra
pairs show one row per invoice/bill allocation combination and may repeat.
Journal pairs have no bill allocation. Use
`apps/update_inter_location_contra_query_table.py --apply` to update the saved
view after changing this query. Updating requires `ZohoAnalytics.modeling.update`.

Run `uv run python apps/propose_inter_location_updates.py` to read the saved
Query Table and create `output/inter_location_location_proposals.md` and its
machine-readable JSON companion. The workflow uses only `Contra pair` rows and
groups allocation rows by pair,
deduplicates invoices and bills, and proposes payment moves only when pairing
references are exact and every allocated invoice and bill has the same location.
Blank-reference pairs, journals, and conflicting document locations stay in
manual review. It never updates Books.

Run `uv run python apps/propose_inter_location_payment_updates.py` to create
`output/inter_location_payment_proposals.md` and JSON for payment-to-invoice
and payment-to-bill mismatches across bank accounts. It groups QT rows by
payment and runs separate Analytics summaries of *all* allocations, including
same-location allocations omitted from the QT. A move is proposed only when
every allocated document resolves to one target location. Mixed or missing
document locations and clearing-account payments remain in manual review.
The proposal output is scoped to FY 2025–26; FY 2026–27 remains available in
the live Analytics Query Table but is omitted from these proposal files.
Analytics can lag Books, so every proposal requires current Books preflight
before an update. The report includes the observed destination payment-number
prefix based on location, financial year of the payment date, and customer or
vendor payment type. The prefix is not an allocated number: the Books location's
assigned series and a unique suffix must be checked before updating both
location and payment number. This app is read-only.

Run `uv run python apps/recheck_inter_location_payment_proposals.py` after
generating the FY 2025–26 payment proposal to read every listed payment from
current Books. Payments already at the proposed destination location are
removed from the Markdown and JSON proposals; an audit of all checked IDs and
their observed locations is saved beside them. Changed payment details or an
unexpected location stay in manual review. This recheck does not update Books.
The payment-number prefix is not proof of a payment's Books location: a payment
whose number already uses the destination series while its Books location is
still the source is held for manual reconciliation.

`apps/move_inter_location_customer_payments.py` calls the reusable
`workflows.inter_location_payment_updates` helper for reviewed FY 2025–26
customer payments. The default batch is up to 15 `SB2526CP-` payments;
the prefix can be selected explicitly for another FY 2025–26 series.
It checks current Books payments,
allocated invoice locations, and destination number collisions before any
mutation. By default it prints a dry run; `--apply` updates location and
number together through a multipart request that suppresses automatic number
generation. It then reads the destination series once in descending order and
verifies every batch payment's ID, number, location, bank account, date, and
amount. A missing or displaced row fails the batch verification.
The next suffix defaults to the highest existing Books number in the selected
series, fetched from the first page with a payment-number prefix filter and
descending payment-number sort. The workflow rejects a response that does not
confirm both query settings. Payments already moved in Books are skipped when Analytics lags;
other changed details fail preflight.

`apps/propose_fy2526_vendor_payment_updates.py` reads the FY 2025–26 vendor
payment candidates from the saved Analytics proposal JSON, verifies current
Books payments and every allocated bill location, and proposes complete
destination numbers from a descending one-page lookup per vendor series. It
excludes payments whose current number already belongs to the destination
series, without consuming a new suffix. This numbered update proposal therefore
does not cover same-series location-only mismatches. It produces Markdown and
JSON review reports without updating vendor payments.

`uv run python apps/apply_remaining_vendor_payment_proposals.py` dry-runs the
current numbered FY 2025–26 vendor proposals. With `--apply`, it requires an
exact match to the outstanding proposal IDs, preflights every payment and bill
across all destination series before any write, then updates and verifies each
series. It records submitted IDs and read-back results in
`output/inter_location_vendor_payment_remaining_apply_audit.json`. Re-run the
Books proposal recheck afterward to remove verified moves from the review file.

`uv run python apps/propose_inter_location_splits.py` reads the remaining FY
2025–26 manual-review payments and every allocated source invoice or bill from
current Books. When one fully allocated payment spans locations, the report
proposes retaining the current-location portion on the original payment and
creating one payment for each other location. It reports exact allocation
amounts and document numbers in `output/inter_location_split_proposals_fy2526.md`
and JSON. Payment `1094368000052871212` is excluded because its SBE portion
was already created separately. The workflow does not change Books.

`uv run python apps/apply_inter_location_updates.py --apply` applies only the
15 reviewed customer payment proposals after verifying all source payments,
contra vendor payments, invoice locations, bill locations, allocations,
references, dates, amounts, and clearing-account IDs in current Books data.
Any preflight failure stops the whole batch before mutations. Each applied
move is read back with its contra and recorded in
`output/inter_location_location_apply_audit.json`. Without `--apply`, the
command performs read-only preflight.
