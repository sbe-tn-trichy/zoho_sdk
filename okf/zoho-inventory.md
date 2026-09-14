---
type: reference
description: Inventory API routing and migration from Books item operations.
---

# Zoho Inventory Client

Item catalog reads, creation, updates, activation/deactivation, item groups,
stock details, bins, and inventory adjustments use `ZohoInventoryAPI` and its
`/inventory/v1` resources. Applications construct it through
`workflows.core.auth.get_inventory_client`, which obtains and refreshes the
Inventory service token. Catalyst mutation authentication requires the requested
service token and no longer implicitly falls back from Inventory to Books.

`inventory.items.list_by_purchase_account(account_id, status="all")` requires a
non-empty purchase account and paginates the scoped results. Status filters use
`filter_by=Status.All`, `Status.Active`, or `Status.Inactive`. Vendor catalog
helpers accept `inventory_client` and preserve purchase-account scoping.

Neoseal audit, export, and naming update applications use Inventory. The audit
includes active and inactive records by default for legacy duplicate detection;
the alias export requests active records. Offline CSV inputs remain supported.
The naming updater retains dry-run, backup snapshots, and per-item audit results.

## Public API migration

- Replace `books.items` and imports from `zoho.books.resources.inventory` with
  `inventory.items` and `zoho.inventory.resources.items`. The Books item resource
  has been removed; it is not a proxy that reuses Books credentials.
- Pass `inventory_client=` to `books.sales_orders.create_from_yaml(...)` for SKU
  lookup and explicitly requested missing-item creation.
- Pass `inventory_client=` to `import_polycab_rso_pdf(...)`; its catalog lookup
  also requires `purchase_account_id`, defaulting to `FAN_PURCHASE_ACCOUNT_ID`.
- Item helper keyword arguments formerly named `books_client` are now
  `inventory_client`.

Books continues to handle accounting transactions and GST location metadata.
Mixed-service sales-order flows use Inventory item IDs in Books order lines.

Endpoint reference: [Zoho Inventory Items API](https://www.zoho.com/inventory/api/v1/items/).
