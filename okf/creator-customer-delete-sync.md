---
type: Concept
title: Creator Customer Sync
description: Books-to-Creator customer creation, update and deletion reconciliation.
---

# Creator Customer Sync

`workflows.creator_customer_sync` treats Books as the source of truth, fetching all
customer contacts (including inactive customers) and all Creator report records.
It matches `Customer_Id` to `contact_id`, creates missing customers, updates changed
mapped fields, leaves identical records alone, and deletes customers absent from Books.
Vendor contacts are excluded locally. Use an unfiltered Creator report containing all customers.

`CreatorCustomerSyncConfig` requires `app_link_name` and `report_link_name`.
Set `form_link_name` to the Creator form link name for creation. `field_mapping`
maps Creator field link names to Books field names and defaults to
`{"Customer_Name": "contact_name"}`. The identity field is always included.
Configure every customer field that should be synchronized; Creator-only fields
are preserved. Missing list fields are fetched using the Books contact detail endpoint;
missing mapped detail fields abort planning instead of clearing data silently.
Values are compared as returned, except customer IDs accept numeric/string equivalence.

```python
from workflows import CreatorCustomerSyncConfig, sync_creator_customers

config = CreatorCustomerSyncConfig(
    app_link_name="customer_app",
    report_link_name="All_Customers",
    form_link_name="Customers",
    field_mapping={"Customer_Name": "contact_name"},
    dry_run=True,
)
summary = sync_creator_customers(books_client, creator_client, config)
```

Dry-run previews all three operations. Candidate counts are separate from actual
mutation counts. Audit JSON defaults to `output/`; an explicit caller output directory
is supported. Deletion limits default to 50 records and 15 percent and are checked
before any writes. Missing Creator IDs/link keys, duplicate keys abort before mutation. Optional `soft_delete_field` and
`soft_delete_value` preserve the existing soft-delete behavior.

Creates and updates run before deletions. API exceptions propagate and stop the run;
previous successful writes are not rolled back. Reports are written on successful completion.

The former `creator_customer_delete_sync` module and exported names remain aliases
for compatibility and now perform full reconciliation, so existing callers must configure
the creation form when customers are missing. The new helper is `sync_creator_customers`.

## Customer scope

Set `books_status_filter="active"` and `books_branch_name="Electricals"` to
limit creates and updates to active Electricals customers. Branch uses the Books
custom field `cf_b_name` by default (`books_branch_field` can override it), with
case-insensitive trimmed comparison and custom-field array fallback. Missing or blank
branch values do not match. Supported status filters are `all`, `active`, and `inactive`.
The workflow still retrieves the complete Books customer set for deletion checks:
customers excluded by status or branch are preserved in Creator. Only customers
absent from Books entirely are deletion candidates. Audit summaries include the
filters and the count of Creator records preserved outside the selected scope.
