---
type: Workflow
title: GSTR-2 Verification
description: Read-only purchase reconciliation cross-checking GSTR-2 / GSTR-2B JSON returns against Zoho Books bills and vendor credits.
tags: [gstr-2, gstr-2b, gst, itc, bills, vendor-credits, purchases, reconciliation]
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
purchases (bills and vendor credits).

## Reconciled Categories

1. **Exact & Normalized Matches**:
   Invoices where document numbers match (via exact or non-alphanumeric normalized
   comparison) and total amounts agree within the configured tolerance (default ±₹1.00).

2. **Value Mismatches**:
   Documents identified by document number and supplier, but exhibiting differences in
   gross value or tax amount exceeding tolerance (e.g. freight, rounding, or entry errors).

3. **In GSTR-2B but Missing in Zoho Books**:
   Transactions reported by suppliers to the GST portal but not recorded as bills or
   vendor credits in Books. Unbooked vendor purchases or direct bank charges where ITC
   remains unavailed are flagged.

4. **In Zoho Books but Missing in GSTR-2B (ITC At Risk)**:
   Bills entered in Zoho Books claiming ITC for which the vendor has not filed GSTR-1.
   Under Section 16(2)(aa) of the CGST Act, ITC cannot be availed in GSTR-3B if missing
   from GSTR-2B.

5. **Ineligible ITC & Reverse Charge**:
   Identifies lines marked as ineligible (`itcavl == 'N'`) or subject to Reverse Charge
   (`rev == 'Y'`).

## Execution

A permanent CLI runner is available at `apps/verify_gstr2.py`:

```bash
python apps/verify_gstr2.py <path-to-gstr2b.json> [--tolerance 1.0] [--output output/report.md]
```

## Related Concepts

See [GSTR-1 Verification](gstr1-verification.md), [Zoho Books Client](zoho-books.md),
and [Package Architecture](architecture.md).
