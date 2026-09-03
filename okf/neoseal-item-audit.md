---
type: reference
---

# Neoseal Item Audit & Nomenclature Review

The Neoseal item audit workflow provides automated data quality analysis of the
Neoseal inventory catalog. It is implemented in `src/workflows/neoseal_audit/`
and exposed as a permanent CLI tool in `apps/audit_neoseal_items.py`.

## Audit Scope & Dimensions

The workflow inspects four key catalog quality dimensions:

1. **Duplicates and Twin Variants**:
   - **Legacy Inactive Pairs**: Identifies inactive catalog records (such as legacy
     `10mtr tape`) that have active standardized counterparts (`10M-YELLOW-12MM`).
   - **Packaging Twins**: Flags identical formulations differing only by container
     type (`(Tin)` vs `(PVC Can)`). These items carry extreme operational risk where
     sales orders and dispatches mismatch, creating negative stock balances.
   - **Near-Duplicate Active Items**: Evaluates high token/character similarity while
     safely distinguishing legitimate size, color, or handle variants.

2. **Item Naming Nomenclature**:
   - **Ball Valves**: Enforces Title Case `GS Plus` over legacy all-caps `GS PLUS`.
   - **Solvents**: Validates `[Grade] [Material] Solution [Pack Size] [Color] ([Container])`.
   - **Tapes**: Checks Title Case color suffixes in parentheses (e.g., `(Blue)` rather than `(BLUE)`).
   - **Chemicals**: Enforces consistent spacing before unit literals (e.g. `10 L` rather than `20L`).

3. **User-Generated SKU Nomenclature**:
   - **Ball Valves**: Verifies `[DecimalSize]-[Material]-[Handle]` (e.g. `0.75-PVC-GSP`).
   - **Solvents**: Verifies `[Grade]-[Size]-[Material]-[Color]-[Container]` and flags inverted
     SKUs starting with volume instead of grade (e.g. `20-PVC-UPVC-CLR-TUBE` ➔ `UPVC-20-CLR-TUBE`).
   - **Tapes**: Verifies `[Length]M-[COLOR]-[WIDTH]`.
   - **Chemicals**: Detects ambiguous bare numbers omitting unit suffixes (`501-1` ➔ `501-1KG`,
     `514-10` ➔ `514-10KG`, `507-10-L` ➔ `507-10L`, `ND40-50` ➔ `ND-40-50`).

4. **Group Assignment & Categorization**:
   - **Missing Groups**: Flags orphaned items lacking a Zoho `group_id` / `group_name`
     (such as `Solvent Rate Difference`, which should be mapped to `Neoseal Adjustment`).
   - **Catch-All Buckets**: Identifies items misplaced in `Solvent Others` (redirecting to
     `UPVC Solvent`) and `Neoseal Others` (redirecting to `Neoseal Maintenance`).

5. **Price List Verification**:
   - Compares each Books item `rate` against an optional price-list CSV using a
     case-insensitive exact SKU match.
   - The price-list CSV must include `sku` and one of `price`, `rate`, or
     `selling_price`. Duplicate price-list SKUs are rejected as ambiguous.

6. **Margin Analysis**:
   - Flags items with missing/non-positive purchase or selling prices, and items
     whose selling price is not greater than their purchase rate.

7. **Pack Size and MRP**:
   - Flags missing or non-positive `pack_size` and `mrp` fields, and MRP values
     below the Books selling price.

8. **Vendor Alias Configuration**:
   - Flags missing `alias_name` values so vendor-facing Neoseal names can be
     configured before matching or purchasing workflows use them.

## Command-Line Usage

### Live Query against Zoho Books

Run directly using the configured Neoseal purchase account:

```bash
python apps/audit_neoseal_items.py \
  --purchase-account-id "$NEOSEAL_PURCHASE_ACCOUNT_ID" \
  --price-list-csv input_files/neoseal/price_list.csv \
  --output output/neoseal_item_audit.md
```

### Offline Snapshot Analysis

Run against an exported CSV snapshot:

```bash
python apps/audit_neoseal_items.py \
  --input-csv output/inventory/neoseal_items_name_vs_sku.csv \
  --output output/neoseal_item_audit.md \
  --json-output output/neoseal_item_audit.json
```

## Public Workflow API

The workflow is exported lazily from `workflows`:

```python
from workflows import NeosealItemAuditor, audit_neoseal_items
from workflows.neoseal_audit import (
    compute_item_update,
    render_markdown_report,
    standardize_item_name,
)

result = audit_neoseal_items(items, price_list=price_list_rows)
report_md = render_markdown_report(result)
```

## Catalog Naming & SKU Updater (`apply_neoseal_name_updates.py`)

A permanent CLI application in `apps/apply_neoseal_name_updates.py` executes approved
nomenclature and SKU updates against live Books items.

- **Safe-by-Default Dry-Run**: Evaluates items and outputs a before/after diff table without mutating Books unless `--apply` is passed.
- **Automated Backup**: Dumps a complete pre-update item snapshot to `output/neoseal_pre_update_snapshot_<timestamp>.json` before any mutations occur.
- **Audit Trail**: Writes a JSON audit report of all applied mutations to `output/neoseal_name_updates_audit.json`.
- **SI Unit Compliance**: Standardizes spacing before unit literals (`1 kg`, `500 g`, `100 ml`, `20 L`, `12 mm`, `10 m`) and replaces non-SI `mtr` with `m`.
- **Duplicate Management**: Identifies zero-stock duplicate items (`701-260-B`, `701-260-W`, `105-500-PVC-CLR-TIN`) and supports optional deactivation via `--deactivate-duplicates`.

```bash
# Dry run inspection
python apps/apply_neoseal_name_updates.py --dry-run

# Commit mutations to Zoho Books
python apps/apply_neoseal_name_updates.py --apply
```
