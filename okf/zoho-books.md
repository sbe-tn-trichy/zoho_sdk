---
type: reference
description: Public resource access patterns for the Zoho Books client.
---

# Zoho Books Client

`ZohoBooksAPI` exposes endpoint-specific resource objects, including `contacts`.
Resources inherit standard CRUD operations and the paginated `list_all()` helper
from `BaseResource`.

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

`chart_of_accounts.list_transactions(account_id, params=None)` returns one API
page from `GET /chartofaccounts/accounttransactions`. The account ID is required;
optional filters such as `date_start`, `date_end`, and amount filters are passed
through without mutating the caller's mapping.

`chart_of_accounts.list_all_transactions(account_id, params=None)` traverses the
endpoint's `page_context` and returns the combined `transactions` list using
200-row pages.

```python
transactions = api.chart_of_accounts.list_all_transactions(
    "123456789",
    {"date_start": "2026-04-01", "date_end": "2026-04-30"},
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
