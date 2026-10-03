---
type: reference
description: Public resource access patterns for the Zoho Books client.
---

# Zoho Books Client

`ZohoBooksAPI` exposes endpoint-specific resource objects, including `contacts`.
Resources inherit standard CRUD operations and the paginated `list_all()` helper
from `BaseResource`.

`bank_transactions.categorize(transaction_id, data)` wraps the native
uncategorized-line categorization endpoint. Cash transfers use
`transaction_type="transfer_fund"`, `from_account_id`, and `to_account_id`.

`bank_transactions.categorize_as_vendor_payment(transaction_id, data)` wraps
the uncategorized-line `categorize/vendorpayments` endpoint. An advance uses
no bill allocations; branch-scoped payments include `location_id`.

`customer_payments.update_with_number_series(payment_id, data)` sends a
multipart `JSONString` payment update with `ignore_auto_number_generation=true`.
Use it when changing location and assigning a specific payment-number prefix
and suffix together; a plain JSON update may let Books assign the location's
current default fiscal-year number instead. Verify the saved payment afterward.

## Reducing a paid bill

`workflows.update_bill_transaction_posting_date(books, bill_id, posting_date,
dry_run=True)` reads the bill's `txn_value_date` and skips the update if it
already equals the requested ISO date. A changed date is sent as a single-field
bill update only with `dry_run=False`, then verified by rereading the bill.
`apps/update_bill_posting_date.py BILL_ID YYYY-MM-DD` previews the change;
`--apply` saves it. A missing saved posting date fails closed rather than
assuming the bill date is equivalent. This uses the Books bill API because it
changes the source transaction; Analytics sync is read-only and may lag.

`workflows.update_bill_with_payment_reallocation()` supports bill updates that
reduce the total below applied vendor payments. It defaults to a dry run and
requires an expected new total. For a decrease, it temporarily unlinks the
bill from each vendor payment, updates the bill, then reapplies payments up to
the new total. Other bill allocations and each bank payment amount are retained;
any excess remains as unapplied vendor payment credit. For a non-decrease it
updates the bill directly. Recheck the returned Books bill and payment credit
after a live run; the API operations are sequential rather than atomic.

## Sales order attachments

`sales_orders.add_attachment(sales_order_id, file_path)` uploads a local file to
`POST /salesorders/{salesorder_id}/attachment`. It validates that the local file
exists before opening it and sends the file as the `attachment` multipart field.
The [Polycab RSO import](polycab-rso-import.md) uses this operation immediately
after creating a Books sales order.

## Customer contacts

`contacts.list_customers(filters=None)` fetches every page of active contacts by
default while always sending `contact_type=customer`. Optional Zoho Books
contact-list filters are copied and forwarded alongside that constraint. The
default `filter_by=Status.Active` can be overridden, but a caller-supplied
`contact_type` cannot override the customer-only behavior, and the input mapping
is not mutated. Because the live Zoho Books API may still include vendor records
despite that query parameter, the SDK also enforces `contact_type=customer` on
the combined response before returning it.

```python
customers = api.contacts.list_customers()
inactive_customers = api.contacts.list_customers(
    {"filter_by": "Status.Inactive"}
)
```

Use `contacts.list()` when a single response page is wanted, or
`contacts.list_all()` for an unqualified paginated contact listing.

## Locations and GST registrations

`locations.list_all(resource_key="locations")` retrieves Books locations from
`GET /locations`. For India organisations, each location includes a
`tax_settings_id`; locations with the same value belong to the same configured
GST registration. The [GSTR-1 verification workflow](gstr1-verification.md)
uses that relationship to keep different GST registrations isolated.

## Financial account transactions

`reports.trial_balance(from_date=..., to_date=..., rule=None, cash_based=False,
show_rows="non_zero")` requests `reports/trialbalance` with opening balance,
net debit, net credit and closing balance columns, preserving the raw response
and Dr/Cr formatting. Use `show_rows="all"` to include zero rows. It validates
date order, basis and any echoed rule. Organization and OAuth authentication
come from the SDK client; browser cookies and CSRF headers are unnecessary.

`workflows.fetch_trial_balance_for_gstin(api, from_date=..., to_date=...,
gstin=...)` applies the registration's configured location scope.
`workflows.fetch_trial_balance_for_firm(api, from_date=..., to_date=..., firm="BD")`
accepts case-insensitive firm aliases with normalized whitespace from
`config/firm-reports.yaml`; identities, GSTINs, default firm and location scopes
are configuration data, with no registration-specific constants in the helper.
Omitting `firm` uses the YAML `default_firm`. Pass `config_path=Path(...)` or set
`FIRM_REPORT_CONFIG` to select another YAML. The older GSTIN helper delegates to
this helper and also accepts configured firm aliases. Unknown firms and invalid
or ambiguous configurations fail before any request. These are reviewed
organization-specific scopes, not automatic discovery from GSTIN.
The helper returns the report without writing files
and supplies the audited comparison's trial-balance snapshot. Public OAuth endpoint
availability still needs live verification; automated tests mock network access.

`reports.profit_and_loss_schedule_format(from_date=..., to_date=..., rule=...)`
requests the schedule-format P&L figures for an explicit ISO date range. The
`zoho.helpers.fetch_profit_and_loss_schedule_format(api, from_date=...,
to_date=..., excluded_location_id=...)` wrapper constructs the Books branch
`not_in` rule and requests accrual basis. The web report's
`profitandloss-scheduleformat` route returned code 5 from the public API;
the SDK therefore uses `reports/profitandloss`, which accepts the same filters
and returns the account totals, though not the web schedule layout.
The request includes `is_expand=true` to ask Books for expanded report rows.

`registers.list_transactions(account_id, *, from_date, to_date, page=1,
per_page=200, cash_based=False)` reads one raw page from the documented Books
account register endpoint. `registers.iter_transactions(...)` traverses
`page_context.has_more_page` and flattens transaction rows from the report's
nested `register_transactions.account_transactions` groups. The SDK always
sends the account ID in the query as well as the path: live Books ignored the
path ID alone and returned the whole ledger. The `*_for_accounts` variants
accept up to 50 IDs and send one comma-separated account filter, matching the
Books API's multi-account option. Dates must be ISO dates and the range must be
ordered. A live request to the web report's apparent
`reports/detailedgeneralledger` path returned Books code 5 (resource not found).

```python
rows = api.registers.iter_transactions(
    "123456789", from_date="2025-04-01", to_date="2026-03-31"
)
```

`zoho.helpers.fetch_equity_general_ledger(api, from_date=..., to_date=...,
excluded_location_id=...)` discovers active and inactive equity accounts and
calls `registers.iter_transactions_for_accounts` once for the whole set. It
resolves the excluded location ID to a unique Books location name, then removes
matching register rows. The register response exposes branch names rather than
IDs; missing or ambiguous branch metadata stops the helper. It returns
`EquityLedgerEntry` records with account metadata and the raw transaction.

`reports.general_ledger(from_date=..., to_date=..., rule=...)` calls the public
`reports/generalledger` endpoint and validates its echoed dates, accrual basis,
and rule columns. `zoho.helpers.fetch_inter_branch_general_ledger` wraps it
with the inter-branch account ID and SBE exclusion and returns debit, credit,
and closing balance. For FY 2025–26, the branch-filtered report returned
debits 14,945, credits 63,120, and a 48,175 credit balance. This is the
relevant figure for the non-SBE reconciliation.

`fetch_inter_branch_register_transactions` separately reads raw postings via
the register SDK and filters branch names. The raw register showed zero amounts
for this account even though the branch-filtered General Ledger was nonzero;
it must not be used to infer the filtered inter-branch balance. The web
`detailedgeneralledger` route is a web route rather than the data endpoint.

`reports.general_ledger_details(account_ids, *, from_date, to_date, page=1,
per_page=500, cash_based=False)` calls `reports/generalledgerdetails`, identified
from a Books browser request. It builds an account-ID `in` rule, uses explicit
custom dates, and selects transaction columns grouped by account. It preserves
the raw response, including report groups and balance rows. The endpoint's
OAuth availability and transaction response schema have not been verified live.
Browser cookies are not used by the SDK.

`reports.iter_general_ledger_details_pages(...)` yields raw pages with a default
100-page bound. It raises on repeated report content, malformed pagination,
wrong echoed page numbers, or an exhausted bound rather than silently returning
an incomplete report. It does not flatten an unverified transaction schema.

```python
page = api.reports.general_ledger_details(
    ["123456789"], from_date="2025-04-01", to_date="2026-03-31"
)
```

`chart_of_accounts.list_transactions(account_id, params=None)` returns one API
page from `GET /chartofaccounts/accounttransactions`. The account ID is required;
optional filters such as `date_start`, `date_end`, and amount filters are passed
through without mutating the caller's mapping.

`chart_of_accounts.list_all_transactions(account_id, params=None)` traverses the
endpoint's `page_context` and returns the combined `transactions` list using
200-row pages. The live endpoint can instead return a `transaction_list` of
transaction-type counts, so use `registers` when detailed posting rows are
required.

```python
transactions = api.chart_of_accounts.list_all_transactions(
    "123456789",
    {"date_start": "2026-04-01", "date_end": "2026-04-30"},
)
```

## Account Transactions report

`reports.account_transactions(account_ids, *, from_date, to_date, page=1,
per_page=500, cash_based=False, response_option=0)` calls the OAuth API route
`reports/accounttransaction`. Option `0` returns raw nested
`account_transactions` groups, opening/closing balances, totals, and
`page_context.has_more_page`. Option `2` returns count metadata in
`page_context.total` and `total_pages`, without transaction rows. Both options
were verified live against the public API.

The method mirrors the browser's ungrouped report with an account-ID `in`
rule, running balance and branch location columns, and explicit custom dates.
It validates the echoed date range, basis, account rule and page, plus the
option-specific payload and pagination fields. It returns a single page;
callers must fetch further pages while `has_more_page` is true. Dates are
required: omitting them can default to the current month. Browser session
headers and CSRF tokens are unnecessary; the client supplies OAuth and
organization scope.

```python
rows = api.reports.account_transactions(
    [account_id], from_date="2022-08-01", to_date="2026-10-31"
)
counts = api.reports.account_transactions(
    [account_id], from_date="2022-08-01", to_date="2026-10-31",
    response_option=2,
)
```

## Bulk contact updates

`contacts.bulk_update(contacts, params=None)` updates multiple contacts through
one `PUT /contacts` request. The SDK serializes the supplied list as the
form-encoded `JSONString` field; the client continues to add
`organization_id` as a query parameter and authenticates with the configured
OAuth access token.

Each contact mapping should contain its `contact_id` and the fields to update:

```python
api.contacts.bulk_update([
    {
        "contact_id": "123456789",
        "custom_fields": [
            {"customfield_id": "987654321", "value": "In Billing"}
        ],
    }
])
```

## Item catalog scoping by purchase account

Item catalog operations use [Zoho Inventory](zoho-inventory.md), including
`inventory.items.list_by_purchase_account(account_id, status="all")` and the
`zoho.helpers.items` helpers with an Inventory client. Purchase-account scoping
prevents cross-vendor item collisions. `ZohoBooksAPI.items` has been removed.

The YAML sales-order importer requires an explicit `inventory_client=` for
item lookup and optional creation; sales-order writes continue through Books.

NeoSeal solvent SKUs use the uppercase, hyphen-separated structure
`Grade-Volume-Type-Color-PackageMaterial`. For example,
`105-500-PVC-CLR-TIN` identifies grade 105, 500 ml, PVC, clear, tin packaging.
The SKU is the stable item identity; display-name normalization must not remove
or merge attributes represented by this structure.

## Domain workflow migration

Customer validation and invoice-YAML imports have moved out of the Books SDK.
Use `workflows.customer_validation.CustomerValidator` and
`workflows.sales_order_import.create_sales_order_from_yaml`; the former SDK
binding/import and sales-order helper method were removed without upward-import
forwarders. See [workflow helpers and migration](workflow-helpers.md).
