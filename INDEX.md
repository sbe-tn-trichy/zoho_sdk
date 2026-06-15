# zoho_sdk — Code Index

> **AI AGENT INSTRUCTION**: Read this file first before opening any source file.
> It maps the entire codebase. Only open source files when you need implementation details beyond what is here.

---

## Project Purpose

Low-level Python SDK providing typed clients for multiple Zoho API services.
Install as `pip install -e .` and import directly; no business logic included.

Supported services:
1. **Zoho Books** — Accounting: invoices, bills, contacts, banking, GST, projects
2. **Zoho WorkDrive** — Cloud file storage: upload, download, move, folders
3. **Zoho Mail** — Email: send, receive, download attachments
4. **Zoho Cliq** — Chat notifications: send messages to channels or bots
5. **Zoho Sheet** — Spreadsheet: read/write rows and cells
6. **Zoho Creator** — Low-code app data: CRUD records, bulk operations
7. **Zoho Inventory** — Inventory management: items, orders, warehouses, batches

---

## Directory Layout

```
zoho_sdk/
├── src/zoho/                        # Installable package (pip install -e .)
│   ├── __init__.py                  # Public API — re-exports all client classes
│   ├── base_client.py               # BaseZohoClient — shared HTTP engine for all services
│   ├── auth.py                      # ZohoOAuth2Manager, CatalystAuth, fetch_token_from_catalyst
│   ├── exceptions.py                # Exception hierarchy (ZohoError and subclasses)
│   ├── logging.py                   # configure_logger() — shared log file setup
│   ├── books/                       # Zoho Books service
│   │   ├── client.py                # ZohoBooksAPI — main client + module wiring
│   │   ├── base.py                  # BaseResource — CRUD base for all resource modules
│   │   ├── mixins.py                # StatusMixin, ApprovalMixin, EmailMixin, CreditsMixin, ActiveInactiveMixin
│   │   └── resources/
│   │       ├── contacts.py          # Contacts, Organizations, ChartOfAccounts, Vendors
│   │       ├── sales.py             # Invoices, Estimates, SalesOrders, CreditNotes, SalesReturns, CustomerPayments
│   │       ├── purchases.py         # Bills, PurchaseOrders, VendorPayments
│   │       ├── banking.py           # BankAccounts, BankTransactions, Journals
│   │       ├── inventory.py         # Items (Books items — not Zoho Inventory service)
│   │       ├── projects.py          # Projects, Tasks, TimeEntries
│   │       ├── gst.py               # GST — validate_gst_data, GSTR reports
│   │       └── customer_validator.py # CustomerValidator — GST/contact data validation
│   ├── wd/                          # Zoho WorkDrive service
│   │   ├── client.py                # ZohoWorkdriveAPI — main client
│   │   ├── base.py                  # BaseResource (WD version)
│   │   └── resources/
│   │       └── files.py             # Files — upload, download, move, folder ops, cleanup
│   ├── mail/                        # Zoho Mail service
│   │   ├── client.py                # ZohoMailAPI — main client
│   │   ├── base.py                  # BaseResource (Mail version)
│   │   └── resources/
│   │       ├── accounts.py          # Accounts — list mail accounts
│   │       ├── folders.py           # Folders — list mail folders
│   │       └── messages.py          # Messages — send, list, download attachments
│   ├── cliq/
│   │   └── client.py                # ZohoCliqAPI — send_notification
│   ├── sheet/
│   │   └── client.py                # ZohoSheetAPI — workbook/sheet/row operations
│   ├── creator/
│   │   └── client.py                # ZohoCreatorAPI — app records CRUD + bulk helpers
│   └── inventory/                   # Zoho Inventory service
│       ├── client.py                # ZohoInventoryAPI — main client + module wiring
│       ├── base.py                  # BaseResource (Inventory version)
│       └── resources/
│           ├── items.py             # Items
│           ├── item_groups.py       # ItemGroups
│           ├── move_orders.py       # MoveOrders
│           ├── transfer_orders.py   # TransferOrders
│           ├── inventory_adjustments.py  # InventoryAdjustments
│           ├── packages.py          # Packages
│           ├── shipments.py         # Shipments
│           ├── picklists.py         # Picklists
│           ├── bins.py              # Bins
│           └── batches.py           # Batches
├── tests/                           # Pytest tests
│   ├── test_auth.py
│   ├── test_books.py
│   ├── test_cliq.py
│   ├── test_creator.py
│   ├── test_inventory.py
│   ├── test_mail.py
│   ├── test_sheet.py
│   └── test_wd.py
├── logs/                            # Runtime log files
└── pyproject.toml                   # Package metadata (name: zoho-sdk, version: 0.1.0)
```

---

## Public API (`from zoho import ...`)

All exports are declared in `src/zoho/__init__.py`.

| Symbol | Type | Service |
|---|---|---|
| `ZohoBooksAPI` | Client class | Zoho Books |
| `ZohoBooksError` | Exception | Zoho Books |
| `ZohoWorkdriveAPI` | Client class | Zoho WorkDrive |
| `ZohoInventoryAPI` | Client class | Zoho Inventory |
| `ZohoInventoryError` | Exception | Zoho Inventory |
| `ZohoMailAPI` | Client class | Zoho Mail |
| `ZohoMailError` | Exception | Zoho Mail |
| `ZohoSheetAPI` | Client class | Zoho Sheet |
| `ZohoCliqAPI` | Client class | Zoho Cliq |
| `ZohoCreatorAPI` | Client class | Zoho Creator |
| `ZohoCreatorError` | Exception | Zoho Creator |
| `ZohoOAuth2Manager` | Auth helper | All services |
| `CatalystAuth` | Auth helper | All services (Catalyst token switching) |
| `ZohoError` | Base exception | All services |
| `ZohoCliqError` | Exception | Zoho Cliq |
| `ZohoSheetError` | Exception | Zoho Sheet |

---

## auth.py — Authentication Helpers

### ZohoOAuth2Manager

Handles OAuth 2.0 token caching, expiry checking, and auto-refresh.

```python
ZohoOAuth2Manager(
    client_id: str,
    client_secret: str,
    refresh_token: Optional[str] = None,    # or use keyring params below
    domain: str = "com",
    access_token: Optional[str] = None,
    expires_at: Optional[float] = None,
    keyring_service: Optional[str] = None,  # alternative to refresh_token
    keyring_username: Optional[str] = None
)
```

| Method | Returns | Notes |
|---|---|---|
| `get_access_token()` | `str` | Returns cached token or calls `refresh_access_token()` if expired |
| `refresh_access_token()` | `str` | POSTs to Zoho OAuth endpoint; caches with 60s buffer |
| `get_token_url()` | `str` | `https://accounts.zoho.{domain}/oauth/v2/token` |

### CatalystAuth

A `str` subclass used as an `access_token` that can switch tokens for mutation requests.

```python
CatalystAuth(direct_token: str, catalyst_token_url: str, service_key: str)
token.get_token_for_request(is_mutation: bool) -> str
```

- For read requests (`is_mutation=False`): returns `direct_token`.
- For mutations (`is_mutation=True`): fetches a fresh token from `catalyst_token_url`.
- Behaves as a plain string when cast to `str` (returns `direct_token`).

### fetch_token_from_catalyst

```python
fetch_token_from_catalyst(url: str, service_key: str) -> Optional[str]
```

POSTs to a local Catalyst token endpoint and extracts `tokens[service_key]` from the response. Returns `None` on any failure.

---

## base_client.py — BaseZohoClient

Shared HTTP engine inherited by all service clients.

```python
BaseZohoClient(
    access_token: Any,
    domain: str,
    base_url: str,
    service_name: str,
    token_refresh_callback: Optional[Any] = None,  # called on 401 to get a new token
    on_request_completed: Optional[Any] = None,    # callback(method, endpoint, json, status, text)
    default_timeout: int = 30
)
```

| Method | Notes |
|---|---|
| `request(method, endpoint, ...)` | Executes HTTP; handles 401 retry, token resolution, logging, streaming |
| `_determine_is_mutation(method, is_mutation)` | Per-service rules for what counts as a mutation (drives CatalystAuth token choice) |
| `_raise_for_status(response)` | Raises service-specific exception for HTTP 4xx/5xx |

**Mutation rules by service:**

| Service | Mutation HTTP methods |
|---|---|
| `books`, `inventory`, `mail` | `PUT`, `DELETE` |
| `wd` (WorkDrive) | `PUT`, `PATCH`, `DELETE` |
| `creator` | `POST`, `PUT`, `PATCH`, `DELETE` |

**Logging:** Each service writes to its own log file under `logs/` (or `tests/logs/` during tests). Set `ZOHO_DISABLE_FILE_LOGGING=true` env var to suppress file logging.

---

## ZohoBooksAPI

```python
ZohoBooksAPI(
    access_token: str,
    organization_id: str,      # required
    domain: str = "com",
    on_request_completed=None,
    token_refresh_callback=None
)
```

Base URL: `https://www.zohoapis.{domain}/books/v3`
`organization_id` is automatically injected into every request's query params.

### Modules (attributes on `ZohoBooksAPI`)

| Attribute | Class | Resource |
|---|---|---|
| `client.organizations` | `Organizations` | `/organizations` |
| `client.contacts` | `Contacts` | `/contacts` |
| `client.vendors` | `Vendors` | `/vendors` |
| `client.invoices` | `Invoices` | `/invoices` |
| `client.estimates` | `Estimates` | `/estimates` |
| `client.sales_orders` | `SalesOrders` | `/salesorders` |
| `client.credit_notes` | `CreditNotes` | `/creditnotes` |
| `client.sales_returns` | `SalesReturns` | `/salesreturns` |
| `client.customer_payments` | `CustomerPayments` | `/customerpayments` |
| `client.bills` | `Bills` | `/bills` |
| `client.purchase_orders` | `PurchaseOrders` | `/purchaseorders` |
| `client.vendor_payments` | `VendorPayments` | `/vendorpayments` |
| `client.bank_accounts` | `BankAccounts` | `/bankaccounts` |
| `client.bank_transactions` | `BankTransactions` | `/banktransactions` |
| `client.journals` | `Journals` | `/journals` |
| `client.chart_of_accounts` | `ChartOfAccounts` | `/chartofaccounts` |
| `client.projects` | `Projects` | `/projects` |
| `client.tasks` | `Tasks` | `/tasks` |
| `client.time_entries` | `TimeEntries` | `/projects/timeentries` |
| `client.items` | `Items` | `/items` |
| `client.gst` | `GST` | (multiple endpoints) |
| `client.customer_validator` | `CustomerValidator` | (composite) |

### BaseResource — Standard CRUD (on every module above)

| Method | Signature | Returns |
|---|---|---|
| `list` | `(params=None)` | `Dict` — API response with resource list |
| `list_all` | `(params=None, resource_key=None)` | `List[Dict]` — auto-paginates (200/page) |
| `get` | `(resource_id, params=None)` | `Dict` — single record |
| `create` | `(data, params=None, files=None)` | `Dict` — validates required fields + merges defaults |
| `update` | `(resource_id, data, params=None, files=None)` | `Dict` |
| `delete` | `(resource_id, params=None)` | `Dict` |

### Mixins

| Mixin | Methods added |
|---|---|
| `StatusMixin` | `mark_as_void`, `mark_as_open`, `mark_as_sent`, `mark_as_draft` |
| `ActiveInactiveMixin` | `mark_as_active`, `mark_as_inactive` |
| `ApprovalMixin` | `submit_for_approval`, `approve` |
| `EmailMixin` | `email(resource_id, data, params=None)` |
| `CreditsMixin` | `apply_credits(resource_id, data)` |

### Module-specific methods

**`contacts` (Contacts)**

| Method | Signature | Notes |
|---|---|---|
| `enable_portal` | `(contact_id, data)` | POST `/contacts/{id}/portal/enable` |
| `email_statement` | `(contact_id, data, params=None)` | POST email |
| `get_statement` | `(contact_id, params=None)` | GET → `bytes` (XLS/PDF) |
| `download_statement` | `(contact_id, save_path, params=None)` | Saves to `output/` if path is relative; default `accept=xls` |

**`vendors` (Vendors)** — same as Contacts plus:

| Method | Signature | Notes |
|---|---|---|
| `get_statement` | `(vendor_id, params=None)` | GET → `bytes` |
| `download_statement` | `(vendor_id, save_path, params=None)` | Saves XLS; default `accept=xls` |

**`invoices` (Invoices)** — Mixins: `StatusMixin`, `EmailMixin`, `ApprovalMixin`, `CreditsMixin`

| Method | Signature | Notes |
|---|---|---|
| `apply_credits` | `(invoice_id, data)` | POST `/invoices/{id}/credits` |

**`estimates` (Estimates)** — Mixins: `StatusMixin`, `EmailMixin`

| Method | Signature | Notes |
|---|---|---|
| `mark_as_accepted` | `(estimate_id)` | POST status/accepted |
| `mark_as_declined` | `(estimate_id)` | POST status/declined |

**`sales_orders` (SalesOrders)** — Mixin: `StatusMixin`

| Method | Signature | Notes |
|---|---|---|
| `create_from_yaml` | `(yaml_str, customer_id, create_missing_items=False)` | Parses flat YAML → resolves items by SKU → creates SO. Optionally creates missing items in Books. |

**`customer_payments` (CustomerPayments)**

| Method | Signature | Notes |
|---|---|---|
| `refund` | `(payment_id, data)` | POST `/customerpayments/{id}/refunds` |

**`bills` (Bills)** — required fields: `bill_number`, `vendor_id`, `date`, `line_items`

| Method | Signature | Notes |
|---|---|---|
| `add_attachment` | `(bill_id, file_content, filename)` | POST multipart file to `/bills/{id}/attachment` |
| `find_duplicate_groups` | `(bills: Iterable)` _(classmethod)_ | Group bill dicts by `bill_number`; returns only groups with >1 entry |
| `list_duplicate_bill_groups` | `()` | `list_all()` + `find_duplicate_groups()` |
| `normalize_bill_number` | `(bill_number)` _(staticmethod)_ | `str(bill_number).strip()` |

**`purchase_orders` (PurchaseOrders)** — Mixin: `StatusMixin`

| Method | Signature | Notes |
|---|---|---|
| `mark_as_billed` | `(po_id)` | POST status/billed |
| `mark_as_cancelled` | `(po_id)` | POST status/cancelled |

**`bank_transactions` (BankTransactions)**

| Method | Signature | Notes |
|---|---|---|
| `match` | `(transaction_id, data)` | POST uncategorized match |
| `categorize_as_expense` | `(transaction_id, data)` | POST categorize as expense |

**`journals` (Journals)**

| Method | Signature | Notes |
|---|---|---|
| `publish` | `(journal_id)` | POST status/publish |

**`items` (Items, Books)** — required: `name`, `sku`, `rate`, `account_id`, `purchase_rate`, `purchase_account_id`, `inventory_account_id`, `is_taxable`, `product_type`, `hsn_or_sac`, `item_tax_preferences`, `unit`, `inventory_valuation_method`, `can_be_sold`, `can_be_purchased`, `track_inventory`

| Method | Signature | Notes |
|---|---|---|
| `list_by_purchase_account` | `(account_id, status="all")` | Filters by `purchase_account_id`; status: `"all"` \| `"active"` \| `"inactive"` |

**`projects` (Projects)** — Mixin: `ActiveInactiveMixin`

| Method | Signature | Notes |
|---|---|---|
| `clone` | `(project_id, data)` | POST clone |

**`time_entries` (TimeEntries)**

| Method | Signature | Notes |
|---|---|---|
| `start_timer` | `(time_entry_id)` | POST timer/start |
| `stop_timer` | `()` | POST timer/stop |

### GST module (`client.gst`)

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `validate_gst_data` | `(month_str: "YYYY-MM")` | `Dict` | Fetches invoices + credit notes for the month; checks sequence gaps, chronology, draft/void status; produces HSN+GST% tax summary |
| `get_gstr_outward_supplies` | `(params=None)` | `bytes` | GET `reports/gstroutwardsupplies` |
| `download_gstr_outward_supplies` | `(save_path, params=None)` | `str` | Downloads GSTR-1 report; default `accept=xlsx` |
| `get_gstr_inward_supplies` | `(params=None)` | `bytes` | GET `reports/gstrinwardsupplies` |
| `download_gstr_inward_supplies` | `(save_path, params=None)` | `str` | Downloads GSTR-2 report; default `accept=xlsx` |
| `get_month_date_range` | `(month_str)` | `(start, end)` | Helper: `"2026-01"` → `("2026-01-01", "2026-01-31")` |

**`validate_gst_data` return shape:**
```python
{
    "month": "2026-01",
    "date_range": ("2026-01-01", "2026-01-31"),
    "invoices": {
        "total_count": int,
        "active_count": int,
        "draft": [{"id": ..., "number": ..., "date": ..., "status": ...}],
        "void": [...],
        "missing": ["SB2627INV-00003", ...],   # sequence gaps
        "out_of_chronology": [{"number": ..., "date": ..., "preceded_by": ..., "message": ...}]
    },
    "credit_notes": { ...same shape... },
    "tax_summary": {
        "invoices":    [{"hsn_or_sac": "8414", "gst_percentage": 18.0, "taxable_value": ..., "tax_amount": ..., "total": ...}],
        "credit_notes": [...],
        "consolidated": [...]    # invoices minus credit notes
    }
}
```

---

## ZohoWorkdriveAPI

```python
ZohoWorkdriveAPI(
    access_token: str,
    domain: str = "in",
    team_id: Optional[str] = None,   # auto-fetched from /users/me if not provided
    token_refresh_callback=None
)
```

Base URL: `https://www.zohoapis.{domain}/workdrive/api/v1`

| Method | Signature | Notes |
|---|---|---|
| `get_team_id()` | `()` | Returns cached `team_id`; fetches from API if not set |

### `client.files` (Files)

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `list_files` | `(folder_id, params=None)` | `Dict` | GET `files/{folder_id}/files` |
| `list_all_files` | `(folder_id, params=None)` | `List[Dict]` | Auto-paginates with `page[limit]=100`, `page[offset]` |
| `upload` | `(folder_id, file_path, file_name=None)` | `Dict` | POST multipart to `/upload?parent_id={folder_id}` |
| `download` | `(file_id, save_path, source_folder_id=None)` | `None` | Streams from `download.zoho.{domain}/v1/workdrive/download/{file_id}` |
| `download_folder` | `(folder_id, destination, *, dry_run=False)` | `List[Path]` | Recursive download; relative `destination` → `output/`; returns list of saved paths |
| `move` | `(file_id, destination_folder_id)` | `Dict` | PATCH parent_id |
| `create_folder` | `(name, parent_id)` | `Dict` | POST `/files` |
| `delete` | `(resource_id)` | `Dict` | DELETE (moves to trash) |
| `search` | `(name, parent_id=None, resource_type="folder")` | `List[Dict]` | GET `organization/{team_id}/records?search[all]=...` |
| `merge_folders` | `(source_id, target_id, folder_name)` | `None` | Recursively moves source contents into target; skips name collisions |
| `cleanup_duplicates` | `(parent_id, recursive=True)` | `None` | Finds timestamped duplicate folders; merges into primary; deletes empty duplicates |
| `get_base_name` | `(name)` | `str` | Strips timestamp/counter suffixes from a folder name |

---

## ZohoMailAPI

```python
ZohoMailAPI(
    access_token: str,
    domain: str = "com",
    token_refresh_callback=None
)
```

Base URL: `https://mail.zoho.{domain}/api`

| Attribute | Notes |
|---|---|
| `client.accounts` | Global `Accounts` resource — `list()` mail accounts |
| `client.account(account_id)` | Returns `AccountScope` with `.folders` and `.messages` bound to that account |

### `AccountScope.messages` (Messages)

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `list` | `(folder_id=None, page=1, limit=50, params=None)` | `Dict` | GET messages/view |
| `list_iter` | `(folder_id=None, start=1, limit=50)` | `Generator` | Yields message dicts until exhausted |
| `get_content` | `(message_id)` | `Dict` | Full message body |
| `send` | `(from_address, to_address, subject, content, **kwargs)` | `Dict` | POST with `"action": "send"` |
| `save_draft` | `(from_address, to_address, subject, content, **kwargs)` | `Dict` | POST with `"action": "save"` |
| `mark_as_read` | `(message_id)` | `Dict` | PUT status=read |
| `mark_as_unread` | `(message_id)` | `Dict` | PUT status=unread |
| `get_attachments_info` | `(folder_id, message_id)` | `Dict` | GET attachment metadata |
| `get_attachment_content` | `(folder_id, message_id, attachment_id)` | `bytes` | Streams content |
| `download_attachment` | `(folder_id, message_id, attachment_id, download_path)` | `str` | Saves; relative path → `output/` |
| `download_folder_attachments` | `(folder_id, download_dir, filename=None)` | `List[str]` | Downloads all attachments from all messages in a folder |
| `message_has_attachment` | `(message)` | `bool` | Checks `hasAttachment` field |
| `extract_attachments` | `(response)` | `List[Dict]` | Normalizes attachment metadata from API response |
| `resolve_download_path` | `(download_dir, attachment_name, sequence_index=None)` | `str` | Returns collision-safe path |

### `AccountScope.folders` (Folders)

| Method | Notes |
|---|---|
| `list()` | Lists folders in the account |

---

## ZohoCliqAPI

```python
ZohoCliqAPI(
    access_token: str,
    bot_name: str = "messengerbot",
    domain: str = "in"
)
```

Base URL: `https://cliq.zoho.{domain}/api/v2`

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `send_notification` | `(message: str, channel: str = None)` | `Optional[Dict]` | If `channel` set: POST `/channels/{channel}/message`; otherwise: POST `/bots/{bot_name}/message`. Returns `None` on failure (non-raising). |

---

## ZohoSheetAPI

```python
ZohoSheetAPI(
    access_token: str,
    domain: str = "in"
)
```

Base URL: `https://sheet.zoho.{domain}/api/v2`
All write operations require `is_mutation=True` (auto-set).

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `list_workbooks` | `()` | `List[Dict]` | GET `workbooks?method=workbook.list` |
| `list_sheets` | `(workbook_id)` | `List[Dict]` | POST `{workbook_id}?method=worksheet.list` |
| `get_rows` | `(workbook_id, sheet_name, limit=1)` | `List[Any]` | Returns `[]` if sheet has no records (error code 2884 suppressed) |
| `set_content` | `(workbook_id, sheet_name, range_addr, data)` | `Dict` | Write range; `data` is `List[List[Any]]`; may return 2867 in some envs |
| `set_cell` | `(workbook_id, sheet_name, row, col, content)` | `Dict` | Single cell write; guaranteed to work in Sheet API v2 |
| `add_sheet` | `(workbook_id, sheet_name)` | `Dict` | Creates a new worksheet |
| `add_rows` | `(workbook_id, sheet_name, rows_data, header_row=1)` | `Dict` | Appends rows; `rows_data` = `List[List]` or `List[Dict]` |
| `update_rows` | `(workbook_id, sheet_name, criteria, rows_data)` | `Dict` | Updates rows matching `criteria` string |
| `truncate_sheet` | `(workbook_id, sheet_name, criteria="(row_index != 0)")` | `Dict` | Deletes rows by criteria (default: all except header) |

---

## ZohoCreatorAPI

```python
ZohoCreatorAPI(
    access_token: str,
    account_owner_name: str,     # e.g. "mycompany"
    domain: str = "com",
    environment: str = "production",
    token_refresh_callback=None
)
```

Base URL: `https://www.zohoapis.{domain}/creator/v2.1`
Header `environment` is injected into every request automatically.

### Metadata APIs

| Method | Signature | Notes |
|---|---|---|
| `list_applications()` | `()` | GET `meta/{owner}/applications` |
| `list_forms` | `(app_link_name)` | GET `meta/{owner}/{app}/forms` |
| `list_reports` | `(app_link_name)` | GET `meta/{owner}/{app}/reports` |
| `get_fields` | `(app_link_name, form_link_name)` | GET `meta/{owner}/{app}/form/{form}/fields` |

### Data APIs

| Method | Signature | Notes |
|---|---|---|
| `get_records` | `(app_link_name, report_link_name, params=None)` | GET up to 1000 records |
| `add_records` | `(app_link_name, form_link_name, payload, params=None)` | POST `{"data": [...]}` |
| `update_records` | `(app_link_name, report_link_name, payload, record_id=None, params=None)` | PATCH by ID or criteria |
| `delete_records` | `(app_link_name, report_link_name, record_id=None, params=None)` | DELETE by ID or criteria |

### Custom SDK Helpers

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `get_all_records` | `(app_link_name, report_link_name, criteria=None)` | `List[Dict]` | Auto-paginates via `record_cursor` |
| `add_records_bulk` | `(app_link_name, form_link_name, records, skip_workflow=None)` | `List[Dict]` | Chunks into batches of 200; returns list of responses |

---

## ZohoInventoryAPI

```python
ZohoInventoryAPI(
    access_token: str,
    organization_id: str,         # required
    domain: str = "com",
    on_request_completed=None,
    token_refresh_callback=None
)
```

Base URL: `https://www.zohoapis.{domain}/inventory/v1`
`organization_id` auto-injected into every request.

### Modules (attributes on `ZohoInventoryAPI`)

| Attribute | Resource |
|---|---|
| `client.items` | Items |
| `client.item_groups` | Item Groups |
| `client.move_orders` | Move Orders |
| `client.transfer_orders` | Transfer Orders |
| `client.inventory_adjustments` | Inventory Adjustments |
| `client.packages` | Packages |
| `client.shipments` | Shipments |
| `client.picklists` | Picklists |
| `client.bins` | Bins (warehouse locations) |
| `client.batches` | Batches (serial/batch tracking) |

All modules expose the standard `BaseResource` CRUD: `list`, `list_all`, `get`, `create`, `update`, `delete`.

---

## exceptions.py — Exception Hierarchy

```
ZohoError (base)
├── ZohoBooksError
├── ZohoInventoryError
├── ZohoWorkdriveError
├── ZohoMailError
├── ZohoCreatorError
├── ZohoCliqError
└── ZohoSheetError
```

---

## logging.py — configure_logger

```python
configure_logger(logger_name: str, log_filename: str) -> logging.Logger
```

- Writes to `logs/{log_filename}` (or `tests/logs/` during pytest).
- Set `ZOHO_DISABLE_FILE_LOGGING=true` to suppress file logging.
- Two format styles: `[API]` for loggers with `"api"` in name; `[APP]` for `"app"` loggers.

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests>=2.25.0` | HTTP calls (only hard dependency) |
| `keyring` | Optional — retrieve OAuth refresh token from OS keychain |
| `yaml` | Optional — used by `SalesOrders.create_from_yaml` |

---

## Common Patterns

**Instantiate a Books client:**
```python
from zoho import ZohoBooksAPI

client = ZohoBooksAPI(
    access_token="your_token",
    organization_id="123456789",
    domain="in"      # "com", "in", "eu", "au", etc.
)
```

**With OAuth auto-refresh:**
```python
from zoho import ZohoBooksAPI, ZohoOAuth2Manager

oauth = ZohoOAuth2Manager(
    client_id="...",
    client_secret="...",
    refresh_token="...",
    domain="in"
)
client = ZohoBooksAPI(
    access_token=oauth.get_access_token(),
    organization_id="...",
    domain="in",
    token_refresh_callback=oauth.get_access_token   # called on 401
)
```

**With CatalystAuth (mutation token switching):**
```python
from zoho import ZohoBooksAPI, CatalystAuth

token = CatalystAuth(
    direct_token="<read_token>",
    catalyst_token_url="http://localhost:3000/tokens",
    service_key="books"
)
client = ZohoBooksAPI(access_token=token, organization_id="...")
```

**Fetch all bills (auto-paginated):**
```python
bills = client.bills.list_all(resource_key="bills")
```

**Upload a file to WorkDrive:**
```python
from zoho import ZohoWorkdriveAPI

wd = ZohoWorkdriveAPI(access_token="...", domain="in")
wd.files.upload(folder_id="abc123", file_path="files/report.pdf")
```

**Download all files from a WorkDrive folder:**
```python
paths = wd.files.download_folder("folder_id", "output/my_folder")
```

**Send a Cliq notification:**
```python
from zoho import ZohoCliqAPI

cliq = ZohoCliqAPI(access_token="...", domain="in")
cliq.send_notification("Task complete!", channel="alerts")
```

**Send an email:**
```python
from zoho import ZohoMailAPI

mail = ZohoMailAPI(access_token="...", domain="in")
acc_scope = mail.account("account_id")
acc_scope.messages.send("from@example.com", "to@example.com", "Subject", "Body")
```

**Get all Creator records (auto-paginated):**
```python
from zoho import ZohoCreatorAPI

creator = ZohoCreatorAPI(access_token="...", account_owner_name="mycompany", domain="in")
records = creator.get_all_records("MyApp", "All_Orders_Report")
```

**Run GST validation for a month:**
```python
result = client.gst.validate_gst_data("2026-01")
print(result["tax_summary"]["consolidated"])
```

---

## Tests

All tests are in `tests/`, one file per service. Run from project root:

```bash
uv run pytest tests/
```

Log output during tests goes to `tests/logs/`. Set `TESTING=true` or run under pytest to activate test log path automatically.
