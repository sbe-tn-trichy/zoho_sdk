---
type: reference
description: Navigation ownership, overlapping commands, and consolidation boundaries.
---

# Project organization

The README is the starting page for setup and navigation. WORKFLOWS.md owns the
business workflow catalog; INDEX.md owns SDK surface navigation. OKF concepts
own detailed operational contracts. Keep detailed instructions in their owning
concept and link to them from the starting pages instead of copying them.

## Overlap and ownership

| Area | Canonical owner | Why related modules remain separate |
|---|---|---|
| Inter-location Analytics Query Table commands | `apps/manage_inter_location_contra_query_table.py` | Create/update filenames are compatibility adapters; update retains its historical saved view ID. |
| Books and Inventory CRUD | `zoho.base_resource.BaseResource` | Service base classes select their exception and logger. |
| Bank statement categorization | `workflows.collection_reconciliation` | Review, generic schema reconciliation and allocation repair have different input and mutation contracts. |
| Payment linking/backfills | `workflows.core.payments` for common evidence | Creator-to-Books and Books-to-Creator writes have opposite directions and conflict rules. |
| Neoseal operations | `neoseal_audit` and `neoseal_stock_count` | Catalog quality and stock-sheet synchronization are distinct operations sharing Inventory access. |

Prefer the Query Table manager for new usage:

```bash
.venv/bin/python apps/manage_inter_location_contra_query_table.py --help
```

Without `--view-id`, it previews creation. With `--view-id ID`, it previews an
update. Both require `--apply` to save. Historical create/update commands delegate
to the same parser and execution path; output wording is now shared.

## Further cleanup boundaries

Large modules worth reviewing include GSTR-2's verifier, collection review, and
Neoseal stock-count reporting. Size alone does not prove duplication. Extract
cohesive parsing, planning or reporting responsibilities with tests before moving
files or merging workflows. Preserve live-state checks, checkpoint recovery,
purchase-account scoping and domain-specific amount/date semantics.

Inter-location proposal, review and execution commands are stages of a workflow,
not automatically duplicate implementations. Keep their review/mutation boundary
visible when simplifying the catalog or adding a unified command.

Related: [Architecture](architecture.md), [shared helpers](workflow-helpers.md),
[workflow catalog](../WORKFLOWS.md).
