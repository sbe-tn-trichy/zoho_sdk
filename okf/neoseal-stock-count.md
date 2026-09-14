---
type: reference
description: Read-only Neoseal stock-count sheets with local grouping and counting order.
---

# Neoseal stock count

`apps/neoseal_stock_count.py` lists active Neoseal catalog items using the
Inventory purchase account, then bulk-fetches item details through
`items.get_details`. It writes the ordered count layout to `Sheet1`, the complete
one-row-per-item detail table to `Flat`, and the SKU-to-cell lookup table to `Mapping` in
Zoho Sheet workbook `m7or01c58bd7a660a4be8b8f2e2390e98c237`.
The dashboard exposes the workflow as `neoseal_stock_count` (entry 16).

```powershell
python apps/neoseal_stock_count.py
python apps/neoseal_stock_count.py --location-id LOCATION_ID
python apps/neoseal_stock_count.py --layout-csv input_files/neoseal/count_layout.csv
python apps/neoseal_stock_count.py --mapping-worksheet Mapping
```

`--purchase-account-id` defaults to `NEOSEAL_PURCHASE_ACCOUNT_ID` and must be
non-empty. Only active items are fetched. Zero and negative quantities remain in
the sheet for review. Every returned item must match the purchase account. Missing,
duplicate, or unexpected item IDs and incomplete detail responses fail the run.

`--sheet-id` can override the configured `NEOSEAL_STOCK_COUNT_SHEET_ID`, and
`--worksheet`, `--flat-worksheet`, and `--mapping-worksheet` can override the default
`Sheet1`, `Flat`, and `Mapping` worksheet names. The workflow creates
the worksheet when it is absent. On later runs it replaces the managed table, removes
stale catalog rows, and preserves manual `physical_count` and `remarks` values
for matching item IDs. Do not add unrelated content to this managed worksheet.

The worksheet follows the sample in `Sheet2`: each group has its own bold 18-point
line, each subgroup follows on a bold 14-point line, and item lines follow beneath.
Item lines show available quantity, unit, blank or retained physical count, remarks,
SKU, item ID, on-hand quantity, and count order in adjacent columns. The first row
holds field names for the Zoho tabular API; group and subgroup lines begin on row 2.
`Flat` retains the previous columns: count order, group, subgroup, item ID, SKU,
name, unit, available quantity, on-hand quantity, physical count, remarks,
original Zoho group, location ID, and generation time. Both views refresh from
the same active Inventory snapshot.

`Mapping` maps each catalog item's `sku` to its target quantity `cell` in `Sheet1`
(along with `item_id`, `name`, and optional `stock_on_hand_cell`). Using this map,
quantities are filled directly into their mapped cells in `Sheet1`. Custom cell
assignments in `Mapping` are preserved across refreshes.

## Quantity meaning

The organization-wide count uses the Inventory item's `available_stock` for
available quantity and `stock_on_hand` for on-hand quantity. A location count
uses only the matching `locations` record's `location_available_stock` and
`location_stock_on_hand`. Missing location records or invalid/non-finite numbers
are reported as unknown, never assumed to be zero. The workflow does not
substitute committed, available-for-sale, or physical stock fields for these
balances. Physical count and remarks columns allow a manual count alongside the
system snapshot; no inventory adjustment is submitted.

Quantities retain decimal precision and each item's unit. No grand total mixes
different units. This is a timestamped snapshot, not an atomic warehouse freeze.

## Groups and count order

Suggested groups, in order, are Solvent cement, Ball valves, Tapes, Sealants,
Construction chemicals, Maintenance, Other items, and Adjustments. Subgroups
use product material/grade, tape type, valve handle, or chemical family. Unknown
items retain their existing Zoho group as a subgroup, or use Unclassified.
The original Zoho group is also retained in the CSV's `source_group` column.
These are local counting labels and do not modify Zoho groups.

Within groups/subgroups, numeric parts of names sort naturally (50 before 100),
then SKU and item ID provide stable tie-breakers. `sort_order` is the final
one-based count sequence. An optional layout CSV can override shelf placement:

```csv
item_id,group,subgroup,group_order,subgroup_order,item_order
123456,Rack A,Top shelf,10,10,1
123457,Rack A,Top shelf,10,10,2
```

Replace example IDs with real catalog IDs. `item_id`, `group`, and `subgroup`
are required. Optional numeric ranks default to 90, 90, and 0 respectively;
lower ranks come first. Group/subgroup ranks apply to the whole named section.
Duplicate IDs, IDs outside the selected count, inconsistent section ranks, and
negative/non-integer ranks are rejected.

## Public APIs

`workflows.neoseal_stock_count` exports `CountPlacement`, `StockCountRow`,
`StockCount`, `StockCountFiles`, `SKUMappingRow`, `default_placement`,
`build_stock_count`, `build_sku_cell_mappings`, `fetch_neoseal_stock_count`,
`render_stock_count`, and `write_stock_count`.
It also exports `StockCountSheetResult`, `write_stock_count_to_sheet`,
`write_flat_stock_count_to_sheet`, `write_mapping_to_sheet`,
`fill_quantities_from_mapping`, `format_cell_address`, and `parse_cell_address`.
`fetch_neoseal_stock_count` is also available from `workflows` and requires an
injected Inventory client. Applications construct the Inventory and Sheet
clients using the auth factories.

The workbook write is the only external mutation: it creates or replaces the
managed worksheet data. It does not update Inventory quantities, create an
inventory adjustment, or reconcile physical counts automatically.
