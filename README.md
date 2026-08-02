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

```python
from workflows import (
    match_bank_with_vendor_ledger,
    process_polycab_credit_memos,
    reconcile_vendor_account,
)
```

The workflow layer builds on the low-level clients and includes bank and vendor
ledger reconciliation, Zeiss statement parsing, and Polycab credit memo
processing. It is a standalone top-level package alongside `zoho`; workflow
code should be imported directly from `workflows`.

Install workflow and test dependencies with:

```bash
pip install -e ".[workflows,test]"
```

Architecture, configuration, and operational guidance is indexed in
[`okf/index.md`](okf/index.md).
