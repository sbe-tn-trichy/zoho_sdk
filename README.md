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
