---
type: Workflow
title: GSTR-2 Verification
description: Read-only purchase reconciliation cross-checking GSTR-2 / GSTR-2B JSON returns against Zoho Books bills, GST-bearing expenses, and vendor credits.
tags: [gstr-2, gstr-2b, gst, itc, bills, expenses, vendor-credits, purchases, reconciliation]
sources:
  - id: workflow-source
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/gstr2_verification/verifier.py
    title: GSTR-2 verification workflow
    author: team:sbe-tn-trichy
    last_modified: 2026-09-22
status: active
---

# GSTR-2 Verification

`workflows.gstr2_verification.verify_gstr2()` performs an evidence-based, read-only
cross-check between a downloaded GSTR-2 or GSTR-2B return JSON file and Zoho Books
purchases (bills, GST-bearing expenses, and vendor credits).

The verifier reads a static registered-GSTIN to Books-location-ID-list snapshot from
`GSTR2_LOCATION_GSTIN_MAP`. The map is maintained in the active configuration
profile. It is
expected to change rarely and should be reviewed when Books locations or GST
registrations change. The workflow does not call the Locations API at runtime.

For a return, it includes only bills, expenses, and vendor credits whose Books
location belongs to the recipient GSTIN in the portal JSON. A document's
`gst_no` identifies the supplier, not the recipient registration. An empty or
invalid map, unknown or missing document locations, or a missing recipient
GSTIN marks the run incomplete; the CLI preserves any existing report in that
case. The report lists the configured Books location IDs included in scope.

Bills are assigned to a return month by Zoho Books `txn_value_date`
(transaction posting date), falling back to bill `date` when no posting date is
provided. The Bills API's documented `date_start`/`date_end` filters apply to
bill date, so the workflow fetches all bills and selects the posting month
locally. Reports retain the supplier bill date for document matching.

Expenses are read from the Books Expenses API for the return period. An expense
joins the ordinary supplier-invoice matching pool only when its forward
`tax_amount`, tax summary, or summed line-item tax is positive. Expenses with
positive `reverse_charge_tax_amount` join only reverse-charge portal matches;
they are excluded from the ordinary supplier-filed GST expense risk list when
unmatched. The workflow loads full expense detail when the list response is
inconclusive or a zero-tax summary has a reference matching a portal RCM
invoice, as Zoho may omit reverse-charge fields from the list. A GSTIN or
`business_gst` treatment alone is not sufficient because an expense may be
exempt or zero-rated.

The Books vendor-credit endpoint is `vendorcredits`, but its list response uses
`vendor_credits`. The verifier explicitly selects that response key when it
fetches period credits and when it looks up a credit by number or reference.

Approved many-to-one purchase entries, including supplier debit notes, can be described in a local JSON map
(`output/gstr2_aggregate_mappings.json` by default). The CLI and dashboard
load this map automatically. A mapping removes individual portal invoices and
the consolidated Books bill from missing sections only when the period,
document type/pattern/date, exact GSTIN set, count, and taxable/tax/gross sums match the
mapped bill. Otherwise the discrepancies remain visible with a mapping warning.
Successful groups appear as one compact row under consolidated purchase matches;
matched portal-document and Books-purchase counts remain distinct.

## Reconciled Categories

1. **Exact & Normalized Matches**:
   Invoices where document numbers match (via exact or non-alphanumeric normalized
   comparison) and total amounts agree within the configured tolerance (default ±₹1.00).
   The verifier also accepts number substring matches when the supplier matches,
   but never matches solely on supplier and amount; that would conflate separate
   invoices with identical values.

2. **Value Mismatches**:
   Documents identified by document number and supplier, but exhibiting differences in
   gross value or tax amount exceeding tolerance (e.g. freight, rounding, or entry errors).
   The report shows portal and Books taxable value, tax, and gross total side by side.
   Books components come from document detail, including vendor-credit tax summaries,
   when available; unavailable values are
   shown as `—`, not as zero.
   For Books documents with an entity-level discount, net taxable subtracts the
   discount only when `is_discount_before_tax` is true. After-tax discounts do
   not reduce taxable value; item-level discounts are already reflected in the
   subtotal and are not subtracted again.

3. **In GSTR-2B but Missing in Zoho Books**:
   Transactions reported by suppliers to the GST portal but not recorded as bills or
   GST-bearing expenses, or vendor credits in Books. Unbooked vendor purchases or direct bank charges where ITC
   remains unavailed are flagged.

4. **In Zoho Books but Missing in GSTR-2B (ITC At Risk)**:
   Bills, GST-bearing expenses, or GST vendor credits entered in Zoho Books for which the vendor has not filed GSTR-1.
   Under Section 16(2)(aa) of the CGST Act, ITC cannot be availed in GSTR-3B if missing
   from GSTR-2B. Commercial credit notes and bills without tax components are categorized
   separately under zero-tax / non-GST documents and excluded from missing ITC alerts.

5. **Ineligible ITC & Reverse Charge**:
   Identifies lines marked as ineligible (`itcavl == 'N'`) or subject to Reverse Charge
   (`rev == 'Y'`).

## Execution

A permanent CLI runner is available at `apps/verify_gstr2.py`:

```bash
python apps/verify_gstr2.py <path-to-gstr2b.json> [--tolerance 1.0]
```

The operations dashboard exposes this workflow as entry 17
(`gstr2_verification`). Its dashboard card accepts a downloaded JSON return,
validates it before launch, and removes the temporary server-side copy when the
verification process exits.

Each successful run writes a timestamped monthly report at
`Output/GSTR2 Verification/monthly/<Mon>-<YYYY>_<DDMM>_<HHMM>.md` (e.g. `Apr-2025_2509_1417.md`).
The report header records the last run time in IST. The same run upserts that month's data
into category-specific CSV histories under
`Output/GSTR2 Verification/cumulative/`, including value mismatches, missing
Books documents, missing GSTR-2B bills/credits/expenses, zero-tax bills,
ineligible ITC, reverse charge, reconciled purchases, aggregate results, vendor
summaries, and monthly summary metrics. New months accumulate in the same
files; re-running an existing month replaces its rows, preventing duplicate
entries. Existing cumulative JSON histories are migrated to CSV on the next
run. `--output` remains available as an exact monthly-report override, and
`--output-root` changes the generated output root.

The CLI refuses to overwrite an existing report when a core Books collection
(bills, expenses, or vendor credits) fails to load.

## Related Concepts

See [GSTR-1 Verification](gstr1-verification.md), [Zoho Books Client](zoho-books.md),
and [Package Architecture](architecture.md).
