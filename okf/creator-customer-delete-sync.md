---
type: Concept
title: Creator Customer Delete-Sync Workflow
description: Delete-only customer reconciliation between Zoho Creator and Zoho Books with safety thresholds and dry-run protection.
tags: [creator, books, customer, sync, delete, safety, reconciliation]
sources:
  - id: creator-customer-delete-sync
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/creator_customer_delete_sync/syncer.py
    title: Creator customer deletion sync workflow
    author: team:sbe-tn-trichy
    last_modified: 2026-08-15
status: active
---

# Creator Customer Delete-Sync Workflow

`workflows.creator_customer_delete_sync` performs unidirectional customer deletion reconciliation between **Zoho Creator** and **Zoho Books**. Creation and update of customer records are handled within Deluge scripts in Zoho Creator. This workflow handles orphan pruning: if a customer record present in Zoho Creator is no longer found in Zoho Books, it is deleted from Zoho Creator.

## Key Design Principles

1. **Delete-Only Scope**: Operates strictly on identifying and deleting (or soft-deleting) Creator records missing from Books.
2. **Dry-Run Protection**: Defaults to `dry_run=True`, which previews candidates and outputs an audit report without making HTTP mutations.
3. **Safety Thresholds**:
   - `max_deletion_limit`: Hard ceiling on the total number of records deleted per run (default: 50).
   - `max_deletion_percentage`: Ceiling on candidate deletion percentage relative to total Creator dataset (default: 15.0%).
4. **Flexible Field Linkage**: Correlates records via `Customer_Id` (or configurable field with case-insensitive fallback lookup) against Books `contact_id` or custom fields.
5. **Soft-Delete Option**: Optional configuration (`soft_delete_field` and `soft_delete_value`) to update a status flag in Creator instead of invoking hard record deletion.

## Standard Usage

```python
from zoho import ZohoBooksAPI, ZohoCreatorAPI
from workflows.creator_customer_delete_sync import (
    CreatorCustomerDeleteSyncConfig,
    sync_creator_customer_deletions,
)

config = CreatorCustomerDeleteSyncConfig(
    app_link_name="customer_app",
    report_link_name="All_Customers",
    creator_id_field="Customer_Id",
    dry_run=True,
)

summary = sync_creator_customer_deletions(
    books_client=books_client,
    creator_client=creator_client,
    config=config,
)
```
