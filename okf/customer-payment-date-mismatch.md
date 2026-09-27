---
type: workflow
description: Read-only audit and safe update workflow for customer payment invoice application dates using Zoho Analytics.
---

# Customer Payment Date Mismatch Check & Update (Analytics)

Run `.venv/bin/python apps/check_customer_payment_dates.py` to audit customer
payments where the recorded payment date differs from the invoice applied dates.

Run `.venv/bin/python apps/update_invoice_payment_dates.py` to preview or apply
corrections setting each applied date to `MAX(Payment Date, Invoice Date)`.

## Logic & Rules

1. **Validity Rule**:
   An applied date is considered valid if:
   $$\text{Applied Date} == \text{Payment Date} \quad \text{OR} \quad \text{Applied Date} == \text{Invoice Date}$$
   Entries violating both conditions are flagged as discrepancies.
2. **Target Applied Date Calculation**:
   $$\text{Target Applied Date} = \max(\text{Payment Date}, \text{Invoice Date})$$
   - If payment date is after invoice date $\rightarrow$ applies on Payment Date.
   - If payment date is before invoice date (advance payment) $\rightarrow$ applies on Invoice Date.

## Workflows & CLI Runners

```bash
# 1. Audit & Export Plan
.venv/bin/python apps/check_customer_payment_dates.py

# 2. Dry-Run Preview of Updates
.venv/bin/python apps/update_invoice_payment_dates.py

# 3. Apply Live Updates to Zoho Books
.venv/bin/python apps/update_invoice_payment_dates.py --execute
```
