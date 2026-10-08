# Workflow Catalog

Implemented domain workflows, grouped by purpose. Code and tests are authoritative. Module links point to reusable library code; permanent runners and review interfaces live in [apps](apps/). Configuration and operational contracts are documented in [OKF](okf/index.md).

## GST

| Workflow | Module |
|---|---|
| GSTR-1 verification | [gstr1_verification](src/workflows/gstr1_verification/) |
| GSTR-2 / GSTR-2B purchase verification | [gstr2_verification](src/workflows/gstr2_verification/) |
| GSTR-3B vs Books P&L comparison | [gstr3b_pnl_comparison](src/workflows/gstr3b_pnl_comparison/) |
| Monthly GST checks | [gst_monthly](src/workflows/gst_monthly.py) |
| GST cash-ledger comparison | [gst_cash_ledger](src/workflows/gst_cash_ledger.py) |

## Financial reporting

| Workflow | Module |
|---|---|
| AIS master reconciliation | [ais_reconciliation](src/workflows/ais_reconciliation/) |
| Audited financial statements and stock comparison | [audited_financials](src/workflows/audited_financials/) |
| Filed IT balance-sheet comparison | [it_balance_sheet_comparison](src/workflows/it_balance_sheet_comparison.py) |
| Books financial-statement sheet updates | [books_statement_sheet](src/workflows/books_statement_sheet.py) |
| Books P&L note preparation | [books_pnl_notes](src/workflows/books_pnl_notes.py) |
| Books account-catalog synchronization | [books_account_catalog](src/workflows/books_account_catalog.py) |

## Bank and ledger reconciliation

| Workflow | Module |
|---|---|
| **Bank Statement Categorization / Collection Reconciliation** | [collection_reconciliation](src/workflows/collection_reconciliation/) |
| Bank–vendor ledger matching | [bank_vendor_ledger_matching](src/workflows/bank_vendor_ledger_matching/) |
| Vendor ledger reconciliation | [vendor_ledger_reconciliation](src/workflows/vendor_ledger_reconciliation/) |

Bank Statement Categorization includes Creator collection matching, Analytics-assisted customer suggestions, reviewed expense categorization, online-payment allocation review and allocation repair. Its entry points are [payment_review.py](apps/payment_review.py), [run_collection_reconciliation.py](apps/run_collection_reconciliation.py) and [repair_review_payment_allocations.py](apps/repair_review_payment_allocations.py). See [operational documentation](okf/collection-reconciliation.md).

## Customer payments

| Workflow | Module |
|---|---|
| Duplicate payment check | [duplicate_payment_check](src/workflows/duplicate_payment_check/) |
| Payment-date checks and corrections | [customer_payment_date_check](src/workflows/customer_payment_date_check/) |
| Customer invoice and payment review | [customer_invoice_payment_review](src/workflows/customer_invoice_payment_review.py) |
| Payment inspection and numbering-series analysis | [payment_inspection](src/workflows/payment_inspection.py) |
| Payment renumbering | [payment_renumbering](src/workflows/payment_renumbering/) |

## Inter-location accounting

| Workflow | Module |
|---|---|
| Contra posting audit and review | [inter_location_contra](src/workflows/inter_location_contra.py) |
| Analytics contra Query Table management | [inter_location_analytics_report](src/workflows/inter_location_analytics_report.py) |
| Payment location-change proposals | [inter_location_location_proposals](src/workflows/inter_location_location_proposals.py) |
| Customer-payment update proposals | [inter_location_payment_proposals](src/workflows/inter_location_payment_proposals.py) |
| Customer-payment location and numbering batch updates | [inter_location_payment_updates](src/workflows/inter_location_payment_updates.py) |
| Live-verified customer-payment location moves | [apply_inter_location_updates](src/workflows/apply_inter_location_updates.py) |
| Payment split proposals | [inter_location_split_proposals](src/workflows/inter_location_split_proposals.py) |
| Vendor-payment move proposals | [inter_location_vendor_payment_proposals](src/workflows/inter_location_vendor_payment_proposals.py) |
| Reviewed vendor-payment updates | [inter_location_vendor_payment_updates](src/workflows/inter_location_vendor_payment_updates.py) |

## Creator synchronization

| Workflow | Module |
|---|---|
| Books-to-Creator customer creation and updates | [creator_customer_sync](src/workflows/creator_customer_sync/) |
| Customer deletion synchronization | [creator_customer_delete_sync](src/workflows/creator_customer_delete_sync/) |
| Customer beat allocation | [creator_beat_allocation](src/workflows/creator_beat_allocation.py) |
| Assigned Creator beats to Books contacts | [creator_beat_sync](src/workflows/creator_beat_sync.py) |
| Books-payment link backfill | [creator_books_payment_link](src/workflows/creator_books_payment_link.py) |
| Online-payment Creator-field backfill | [online_payment_creator_backfill](src/workflows/online_payment_creator_backfill.py) |

## Customers and sales

| Workflow | Module |
|---|---|
| Customer contact validation | [customer_validation](src/workflows/customer_validation/) |
| Sales-order import from invoice YAML | [sales_order_import](src/workflows/sales_order_import/) |
| Polycab return-sales-order PDF import | [polycab_rso](src/workflows/polycab_rso/) |

[register_customer.py](apps/register_customer.py) additionally supports Creator customer-registration form inspection and record creation directly in the application layer.

## Vendor transactions

| Workflow | Module |
|---|---|
| Polycab credit-memo processing and attachments | [polycab_credit_memos](src/workflows/polycab_credit_memos/) |
| Polycab vendor-credit review and correction | [polycab_credit_review](src/workflows/polycab_credit_review/) |
| GSTIN-checked vendor–customer payment offset | [vendor_customer_offset](src/workflows/vendor_customer_offset/) |
| Bill updates with payment preservation and posting-date updates | [bill_updates](src/workflows/bill_updates.py) |

## Inventory and Neoseal

| Workflow | Module |
|---|---|
| Neoseal item audit, catalog export and name updates | [neoseal_audit](src/workflows/neoseal_audit/) |
| Neoseal stock count, sheet formatting and synchronization | [neoseal_stock_count](src/workflows/neoseal_stock_count/) |
| Paired stock transfer | [stock_transfer](src/workflows/stock_transfer/) |

## Running workflows

Run applications from the repository root using the workspace environment. For example:

```powershell
uv run python apps/payment_review.py --help
uv run python apps/verify_gstr2.py --help
uv run python apps/neoseal_stock_count.py --help
```

Use each app's help and relevant OKF documentation for configuration, arguments and mutation controls. Some workflows are library APIs without a dedicated runner. [dashboard.py](apps/dashboard.py) provides a launcher for common workflows.

## Shared infrastructure

[workflows.core](src/workflows/core/) contains authentication factories, configuration, matching, dates, sequences, checkpoints, snapshots and payment primitives. It is shared infrastructure rather than a standalone business workflow. Empty and cache-only directories are excluded from this catalog.

Customer registration in Books and Creator: [customer_registration](src/workflows/customer_registration/), run with [register_customer.py](apps/register_customer.py). See [usage and recovery](okf/customer-registration.md).

Creator customer-number backfill: [sync_customer_numbers.py](apps/sync_customer_numbers.py), using [customer_registration](src/workflows/customer_registration/) with explicit Books IDs and a dry-run default.
