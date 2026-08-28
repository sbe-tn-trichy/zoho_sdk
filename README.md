# Zoho SDK

Decoupled SDK for Zoho API services including Books, Inventory, Creator,
Analytics, WorkDrive, Mail, Cliq, and Sheet.

## Installation

Install locally in editable mode:
```bash
pip install -e .
```

## Configuration

This SDK does not load credentials from local files or environment variables. Credentials must be passed explicitly to the constructors.

Tokens are never persisted by the SDK. `HttpTokenProvider` retrieves tokens at
runtime from a configured HTTP token broker and keeps no token cache. Its
representation is redacted, and callers should never log token values or
authorization headers.

## Zoho Analytics dynamic queries

Dynamic SQL `SELECT` queries use Zoho Analytics' asynchronous bulk export API:

```python
from zoho import ZohoAnalyticsAPI

analytics = ZohoAnalyticsAPI(
    access_token="...",
    organization_id="...",
    domain="in",
)
rows = analytics.views.query_data(
    workspace_id="...",
    sql_query='SELECT * FROM "Sales"',
)
```

The SDK creates an export job, polls it, downloads the result as CSV, and
returns a list of dictionaries.

### Download complete workspace metadata

The Analytics client can create a resumable, indexed metadata snapshot
containing the workspace, folders, data sources, views, table columns, and a
normalized relationship map:

```python
from zoho import ZohoAnalyticsAPI

analytics = ZohoAnalyticsAPI.from_token_provider(
    token_service_key="zoho_analytics_conn",
    organization_id="...",
    domain="in",
)
manifest = analytics.metadata.download_workspace(
    workspace_id="...",
    output_dir="workspace_metadata",
    include_column_dependents=False,
    requests_per_minute=50,
    resume=True,
    show_progress=True,
)
```

The output directory contains `metadata.sqlite` for fast indexed access and a
compact `summary.md` for human review. Use the snapshot reader without loading
the complete workspace into memory:

```python
from zoho.analytics import WorkspaceMetadataStore

with WorkspaceMetadataStore("workspace_metadata/metadata.sqlite") as metadata:
    views = metadata.find_views("Accounts")
    columns = metadata.get_columns(views[0]["view_id"])
    links = metadata.get_relationships("view:" + views[0]["view_id"])
```

`from_token_provider()` uses
`http://localhost:3000/server/new/tokens` by default; pass `token_url` only to
override the broker location. The `zoho_analytics_conn` service key falls back
to the broker's `analytics` token key.

The collector requires the `ZohoAnalytics.metadata.read` OAuth scope. It
paces requests below Zoho's metadata frequency limit, retries `6045` and HTTP
429 responses, prints rate-limit and recovery messages immediately, and saves
progress inside the SQLite snapshot so an interrupted run can resume without
refetching completed views.

Later refreshes can use incremental synchronization:

```python
result = analytics.metadata.sync_workspace(
    workspace_id="...",
    output_dir="workspace_metadata",
)
print(result["sync"])
```

The view inventory is fetched 200 rows at a time. Only new or modified views
have their details and table columns fetched again; deleted views are removed
locally. Content hashes avoid rewriting SQLite rows when Zoho's modification
timestamp changes but the metadata content does not.

## Business workflows

Higher-level reconciliation and credit-memo operations are available under
`workflows`:

### Local operations dashboard

Launch the numbered startup page for frequently used, safe-default workflows:

```bash
python scripts/project_dashboard.py
```

Open `http://127.0.0.1:8750`, enter a workflow number, and press Enter. The
dashboard runs only its fixed command allowlist, shows live status and recent
output, and links to local workflow UIs when available. Commands that mutate
Zoho are not exposed with their live execution flags.

```python
from workflows import (
    CollectionReconciliationConfig,
    GSTR1VerificationConfig,
    import_polycab_rso_pdf,
    match_bank_with_vendor_ledger,
    process_polycab_credit_memos,
    reconcile_collections,
    reconcile_vendor_account,
    verify_gstr1,
)
```

Run the read-only GSTR-1 readiness checks for the previous calendar month:

```python
report = verify_gstr1(
    books_client,
    config=GSTR1VerificationConfig(e_invoice_applicable=True),
)
```

The workflow reports draft invoices and credit notes, financial-year-aware
number gaps and chronology errors, and applicable e-invoices that are not
successfully registered with an IRN. Locations sharing a Books
`tax_settings_id` are checked together as one GST registration; different GST
registrations are never combined. Pass `month="YYYY-MM"` to audit an explicit
month. The workflow never pushes or modifies Books transactions.

The workflow layer builds on the low-level clients and includes bank and vendor
ledger reconciliation, Zeiss statement parsing, and Polycab credit memo
processing. It is a standalone top-level package alongside `zoho`; workflow
code should be imported directly from `workflows`.

Import one machine-readable Polycab RSO PDF as a Books sales order and attach
the source document:

```bash
python scripts/import_polycab_rso.py /path/to/RSO_262707003493.pdf
```

The parser reads only the first `ITEM DETAILS` table and stops at `Total Rs.`,
so the repeated `LINE DETAILS` table is not imported. The customer and Sri
Bharath Electricals location defaults can be overridden with `--customer-id`
and `--location-id`.

### Creator collection reconciliation

```python
from workflows import CollectionReconciliationConfig, reconcile_collections

config = CollectionReconciliationConfig(
    creator_app_link_name="collections-app",
    bank_account_id="...",
    analytics_workspace_id="...",
    dry_run=True,
)

result = reconcile_collections(
    creator_client=creator,
    books_client=books,
    analytics_client=analytics,
    config=config,
    validate_schema=True,
)
```

The workflow validates the Creator collection and audit forms, validates the
two required Books customer-payment custom fields, matches date/amount/reference
without auto-selecting ambiguous transactions, and returns Analytics suggestions
for manual exceptions. Set `dry_run=False` only after reviewing the validation
and match output. Pass `create_missing_books_fields=True` to explicitly create
missing Books fields; Creator form fields must be configured in Creator.

For the production Creator `Online_Payments` report, launch the local human
review queue instead:

```bash
python scripts/review_online_payments.py
```

Open `http://127.0.0.1:8765`. The queue maps the live `Payments` form fields and
the `All_Customers1.Customer_Id` Books identifier, proposes unique
date/amount/reference bank matches, and persists accept/reject decisions under
`output/collection_reconciliation/`. Rejecting is local-only. `Accept & Push`
revalidates the live bank line, refreshes the customer's open Books invoices,
allocates the payment oldest-due-first, creates or reuses a checkpointed Books
customer payment, matches it to the bank transaction, and writes the payment ID
to the Creator `Books_Transaction_Id` field. Rows with no open invoice are
blocked so the full payment cannot accidentally become unused credit. If open
invoice balances are lower than the payment, the preview shows the exact excess
that will remain unused. The server binds only to loopback and requires a
per-process confirmation token for mutations.
Use `Select all ready` followed by `Accept selected & Push` to approve every
eligible match with one confirmation. The backend reuses one live bank snapshot
and processes the selected pushes sequentially, returning isolated failures.
By default the same page combines HDFC, ICICI, and IDFC proposals and displays
the originating bank in a dedicated column. It also combines Creator's
`Online_Payments` and `Cheques` reports, labels the payment type, and uses the
`Presented_Date` from Creator's `All_Cheque_Details` report and Books `check`
payment mode for cheque rows. Cheque details are joined uniquely by normalized
cheque number and customer; an unpresented or ambiguous cheque is not eligible.

To repair legacy queue-created payments whose amount was left as unused credit,
run `python scripts/repair_review_payment_allocations.py` for a read-only plan,
then add `--execute`. The repair updates each existing payment in place,
preserves previous invoice allocations, applies only its live unused amount
oldest-due-first, verifies the resulting unused balance, and writes an atomic
checkpoint under `output/collection_reconciliation/`.

To backfill the reciprocal Creator identifiers onto existing Books customer
payments from Creator's `matched` report, run the guarded temporary script:

```bash
python scripts/backfill_creator_matched_payments.py
```

The default is read-only and writes JSON/CSV assessment files under `output/`.
A write run must use `--execute` with either `--creator-record-id ID` for one
payment or the additional `--allow-batch` flag. The script only updates the
`Creator Record ID` and `Creator Payment ID` custom fields; it never creates a
payment or changes a bank match. Incremental checkpoints support safe restart.

Install workflow and test dependencies with:

```bash
pip install -e ".[workflows,test]"
```

Architecture, configuration, and operational guidance is indexed in
[`okf/index.md`](okf/index.md).

### Duplicate customer-payment check

Run a read-only Books API check for payments sharing the same customer ID,
payment date, and amount:

```bash
python scripts/check_duplicate_customer_payments.py
```

Use `--from-date YYYY-MM-DD`, `--to-date YYYY-MM-DD`, or `--customer-id ID` to
limit the report. A compact customer/date-grouped Markdown report is saved to
`output/duplicate_customer_payments.md`. Pass `--output report.html` for the
searchable HTML table.
