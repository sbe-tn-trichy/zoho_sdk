---
type: reference
description: Public resource access patterns for the Zoho Books client.
---

# Zoho Books Client

`ZohoBooksAPI` exposes endpoint-specific resource objects, including `contacts`.
Resources inherit standard CRUD operations and the paginated `list_all()` helper
from `BaseResource`.

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
