---
type: reference
description: Inventory quantity upserts into the Neoseal Flat stock-count sheet.
---

# Neoseal stock count

`apps/neoseal_stock_count.py` lists active Neoseal catalog items using the
Inventory purchase account, keeps only items with `track_inventory=true`, then
bulk-fetches their details through
`items.get_details`. It updates existing item rows by `item_id` and appends
missing items in the `Flat` worksheet of the configured Zoho Sheet workbook.
The command leaves `StockCount` and `Mapping` untouched. Flat begins with
`item_id`, `sku`, and `name`; it has no sort-order, group, or subgroup columns.
After upserting Flat rows, it lists existing
Flat items absent from the current active, inventory-tracked Inventory fetch,
including their item IDs, SKUs, and names. It does not delete them by default.
Existing `physical_count` and `remarks` cells remain unchanged.
The bulk item detail's `cf_pack_size` custom field (`Pack Size`) is written to
Flat's trailing `packing` column for both existing and new items. An absent
custom-field value becomes blank. The column is appended after `generated_at`
in column L; an occupied column L with a
different header stops the upsert.
The dashboard exposes the workflow as `neoseal_stock_count` (entry 16).

```powershell
python apps/neoseal_stock_count.py
python apps/neoseal_stock_count.py --location-id LOCATION_ID
python apps/neoseal_stock_count.py --flat-worksheet Flat
python apps/neoseal_stock_count.py --delete-missing-item-id APPROVED_NUMERIC_ID
```

`--purchase-account-id` defaults to `NEOSEAL_PURCHASE_ACCOUNT_ID` and must be
non-empty. Only active, inventory-tracked items are fetched. A missing or invalid
`track_inventory` flag fails the run; items with `track_inventory=false` are
excluded before the bulk detail request. Previously written Flat rows for
excluded items are reported as missing but not deleted unless their exact IDs
are explicitly passed with `--delete-missing-item-id` after review and approval.
Before deleting, the workflow checks the current Flat sheet and the freshly
fetched Inventory snapshot again; it rejects IDs that are no longer missing.
Approved rows are deleted from the bottom upward. Flat reads use grid content
as well as the tabular API because blank row positions after deletion can make
tabular fetch stop early, hiding later rows and causing duplicate appends.
Zero and negative quantities remain in
the sheet for review. Every returned item must match the purchase account. Missing,
duplicate, or unexpected item IDs and incomplete detail responses fail the run.

`--sheet-id` can override `NEOSEAL_STOCK_COUNT_SHEET_ID`, and
`--flat-worksheet` can override `NEOSEAL_STOCK_COUNT_FLAT_WORKSHEET` (`Flat`).
The command creates the Flat worksheet when absent. Duplicate `item_id` rows
or an existing Flat sheet at the 1,000-row read limit stop the run to prevent
ambiguous updates.
An existing Flat worksheet must have the expected columns in order, and every
populated item ID must be numeric; otherwise the command stops before writing.
The table is bulk-refreshed in two API operations: existing data rows are cleared via
`worksheet.records.delete` with `criteria='"item_id" != \'\''` (preserving Row 1 headers),
and all merged rows (retaining physical counts, remarks, and unapproved missing
items) are re-added in a single `worksheet.records.add`
operation.

The grouped `StockCount` and `Mapping` helpers remain public for separate,
explicit operations, but the main command no longer calls them.

The separate grouped-sheet helper follows the sample in `Sheet2`: each group has its own bold 16-point
line, each subgroup follows on a bold 14-point line, and item lines follow beneath (10-point, regular).
Item lines show available quantity, unit, blank or retained physical count, remarks,
SKU, item ID, on-hand quantity, and count order in adjacent columns. The first row
holds field names for the Zoho tabular API; group and subgroup lines begin on row 2.
`Flat` contains item ID, SKU, name, unit, available quantity, on-hand quantity,
physical count, remarks, original Zoho group, location ID, generation time, and
packing. The main command updates ungrouped item details in `Flat`.

The separate mapping helpers maintain `Mapping`, which maps each catalog item's
`sku` to its target quantity `cell` in `StockCount`
(along with the product `name` displayed in `StockCount`, `item_id`, and optional
`stock_on_hand_cell`). Columns A–C are SKU, Cell, and Name respectively. Unmapped
items have a blank Cell and Name. Mapping refresh reads the current `StockCount`
label for each mapped cell and rejects a missing label. Using this map,
quantities are filled directly into their mapped cells in `StockCount`. In the dual-table
`StockCount` layout, system inventory available stock is written into the `QTY` columns
(Column `C` for the left table, Column `H` for the right table), while the `AVL` columns
(Column `D` and Column `I`) remain intentionally blank. Custom cell assignments in
`Mapping` are preserved across refreshes, and intentionally unmapped items (`cell=""`)
are protected from accidental fallback overwrites.
The live count page's mapped QTY cells use Zoho Sheet `SUMIF` formulas against
Flat column B (SKU) and column E (`available_quantity`). The stable sync
operation writes the SKU directly into each formula, so rebuilding or reordering
Mapping cannot redirect it to another item. Multiple SKUs assigned to one line
produce summed `SUMIF` terms. PACK formulas look up Flat column L (`packing`)
by SKU and retain the previous displayed Pack when Flat packing is blank;
unmapped lines use literal Pack formulas and zero QTY formulas.
`apps/sync_neoseal_stockcount.py` is a dry-run by default and uses `--apply` for
API mutations. It stores persistent count-line IDs in StockCount columns J/K
and Mapping column F. On subsequent runs it finds moved lines by ID, corrects
Mapping's QTY cell address in column B, and rebuilds formulas whose expressions
changed. New Flat SKUs without Mapping rows are reported for placement; new
StockCount product lines receive IDs when they have a product label and a PACK
or QTY value. The formula range expands from the Flat used row with a buffer
at each sync, rather than relying on a permanent 1,000-row ceiling.
When multiple SKUs map to a single consolidated row in `StockCount` (such as multiple
insulation tape colors or silicone colors), `fill_quantities_from_mapping` sums the
available quantities across all matching items for that target cell.
For the custom two-table layout, `zero_unmapped_stockcount_quantities` writes `0` to
the QTY cell of each product line with no mapped SKU. It leaves mapped quantities
and category lines alone; a product line is identified by a product label plus a
PACK or existing QTY value.

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

## Separate grouped-sheet helpers

The library's `build_stock_count` helper still supports suggested groups, in
order: Solvent cement, Ball valves, Tapes, Sealants,
Construction chemicals, Maintenance, Other items, and Adjustments. Subgroups
use product material/grade, tape type, valve handle, or chemical family. Unknown
items retain their existing Zoho group as a subgroup, or use Unclassified.
The original Zoho group is also retained in the CSV's `source_group` column.
These are local counting labels and do not modify Zoho groups.

Within groups/subgroups, numeric parts of names sort naturally (50 before 100),
then SKU and item ID provide stable tie-breakers. `sort_order` is the final
one-based count sequence. A caller can provide a layout mapping built from rows
like these to override shelf placement:

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
`StockCount`, `StockCountFiles`, `SKUMappingRow`, `CUSTOM_STOCK_COUNT_MAPPING`,
`default_placement`, `build_stock_count`, `build_sku_cell_mappings`,
`fetch_neoseal_stock_count`, `render_stock_count`, and `write_stock_count`.
It also exports `StockCountSheetResult`, `write_stock_count_to_sheet`,
`write_flat_stock_count_to_sheet`, `write_mapping_to_sheet`,
`fill_quantities_from_mapping`, `format_custom_stock_count_sheet`,
`zero_unmapped_stockcount_quantities`,
`format_cell_address`, and `parse_cell_address`.
`apps/format_stock_count.py` formats category cell merges and borders via the Sheet API.
`fetch_neoseal_stock_count` is also available from `workflows` and requires an
injected Inventory client. Applications construct the Inventory and Sheet
clients using the auth factories.

The main stock-count command's workbook write upserts Flat worksheet rows. The
separate stable sync mutates StockCount and Mapping through the Sheet API. Neither
operation updates Inventory quantities, creates an
inventory adjustment, or reconciles physical counts automatically.
