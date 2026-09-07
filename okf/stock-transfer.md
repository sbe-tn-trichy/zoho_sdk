---
type: reference
---

# Paired Books stock replenishment

`apps/transfer_stock.py` prepares and posts a Books invoice at a source location
and a matching bill at a destination location. Select explicit item IDs through
an `item_id` CSV column, purchase accounts, contact IDs, locations, transaction
date, and a unique reference. Dry-run is the default; `--apply` creates the pair.
The supported scope is distinct GST registrations in the same state. Invoice
customer GSTIN must match the destination; bill vendor GSTIN must match the source.

`workflows.stock_transfer` exports `TransferLine`, `build_plan`, `build_payloads`,
and `validate_stock`. Each line rate is the item purchase rate plus a fixed 3%
markup. Quantities are the minimum of destination accounting-stock
shortage and source accounting, physical, and uncommitted stock. Negative or zero
source availability produces no transfer. Invalid/missing stock fails closed.
Bin-enabled source items also require item-specific bin balances from
`GET /storagelocations`; allocations never exceed positive active-bin balances.
Bin reads are paced at one per second; location balances are bulk-refreshed
after each bin pass. The same bins are rechecked before posting. Batch/serial tracked items require
allocations and are rejected. Both documents use the same rates, quantities and
intra-state tax; bills debit the inventory account.

The CLI requires `--maximum-invoice-total`, `--starting-date`, and
`--ending-date`. The threshold includes tax. It splits item quantities across
multiple matched invoice/bill pairs so each invoice stays at or below the cap.
Dates are assigned across the inclusive range in order, cycle when there are
more documents than dates, and always exclude Sundays.

`ZohoInventoryAPI.items.get_details(item_ids, batch_size=50)` uses the documented
[`GET /itemdetails`](https://www.zoho.com/inventory/api/v1/items/#bulk-fetch-item-details)
endpoint, deduplicates requests and rejects incomplete/unexpected responses.
`workflows.core.auth.get_inventory_client` constructs the Inventory client with
its own token and refresh callback.

The application writes its plan and execution journal under
`output/stock_transfer/<reference>/`. It checks for existing references before
creation, validates each returned draft, and checks live stock again before
posting. It marks invoices sent without emailing and opens bills, then reads back
both documents and verifies nonnegative source accounting stock. No physical
package, shipment, receipt, payment, or e-invoice submission is created.

## Partial execution and concurrency

Zoho does not provide an atomic operation covering this pair and the stock read.
Other writers can change stock between the final check and posting. The workflow
cannot guarantee isolation from concurrent sales. Run during a quiet period and
inspect the post-transfer stock verification.

A journal is persisted before each mutation. Any subsequent execution with the
same journal is blocked, including after an uncertain API response. Inspect the
recorded stage and live Books reference/IDs, and recover the existing pair rather
than creating duplicates. A failed draft validation leaves the draft available
for correction; a failure after invoice posting requires completing or correcting
the existing bill. The workflow does not automatically void or delete records.
