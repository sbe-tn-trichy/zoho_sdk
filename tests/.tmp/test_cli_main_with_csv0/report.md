# Neoseal Inventory Item Audit & Nomenclature Report

- **Audited At:** 2026-09-03 18:21:39 UTC
- **Data Source:** Local CSV (test_items.csv)
- **Total Items:** 11 (Active: 10, Inactive: 1)

---

## Executive Summary

| Audit Check | Status | Issues Found | Focus / Recommendation |
| :--- | :---: | :---: | :--- |
| **1. Duplicates & Twins** | ⚠️ Warning | 2 | Flagged packaging twins (Tin vs Can) & legacy duplicates |
| **2. Naming Nomenclature** | ⚠️ Warning | 2 | Standardize Title Case (`GS Plus`, parenthetical tape colors) |
| **3. User-Generated SKUs** | ⚠️ Warning | 4 | Solvent structure inversion & missing chemical unit suffixes |
| **4. Group Categorization** | ⚠️ Warning | 3 | Unassigned Zoho item groups & catch-all buckets |
| **5. Price List** | ✅ Clean | 0 | Books selling price must match the supplied price list |
| **6. Margin** | ⚠️ Warning | 11 | Positive margin requires selling price above purchase rate |
| **7. Pack Size & MRP** | ⚠️ Warning | 22 | Pack size and MRP must be positive values |
| **8. Vendor Alias** | ⚠️ Warning | 11 | Each item needs its Neoseal vendor alias |

---

## 1. Duplicates & Twin Variants

| Type | Item A (Status / SKU / Stock) | Item B (Status / SKU / Stock) | Risk / Details |
| :--- | :--- | :--- | :--- |
| **Packaging Twin** | `200 UPVC Solution 100ml Blue (PVC Can)`<br>(active, SKU: `200-100-UPVC-BLU-CAN`, Stock: -9.0) | `200 UPVC Solution 100ml Blue (Tin)`<br>(active, SKU: `200-100-UPVC-BLU-TIN`, Stock: 361.0) | Packaging twin (Tin vs PVC Can). Identical formulation and volume; high risk of stock mismatch and negative billing entries. |
| **Legacy Duplicate** | `PTFE Tape Premium 12mm 10mtr`<br>(inactive, SKU: `10mtr tape`, Stock: 0.0) | `PTFE Tape Premium 12mm 10mtr Yellow`<br>(active, SKU: `10M-YELLOW-12MM`, Stock: 1654.0) | Legacy duplicate pair: 'PTFE Tape Premium 12mm 10mtr' [inactive] vs 'PTFE Tape Premium 12mm 10mtr Yellow' [active]. |

---

## 2. Item Naming Nomenclature Issues

| Current Name | Current SKU | Issue Description | Recommended Name |
| :--- | :--- | :--- | :--- |
| `1 1/4" PVC Ball Valve GS PLUS` | `1.25-PVC-GSP` | Uses uppercase 'GS PLUS' instead of Title Case 'GS Plus'. | **`1 1/4" PVC Ball Valve GS Plus`** |
| `PVC Insulation Tape 6mtr (BLUE)` | `6M-INSULATION-BLUE` | Parenthetical color '(BLUE)' is all-caps. | **`PVC Insulation Tape 6mtr (Blue)`** |

---

## 3. User-Generated SKU Nomenclature Issues

| Item Name | Current SKU | Issue Type | Recommendation | Details |
| :--- | :--- | :--- | :--- | :--- |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | inverted_sku_structure | **`UPVC-20-CLR-TUBE`** | SKU starts with package size ('20') instead of product type/grade. |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | legacy_sku_format | **`10M-WHITE-12MM`** | Legacy unstandardized tape SKU '10mtr tape'. |
| `501 SBR Latex 1kg` | `501-1` | missing_unit_suffix | **`501-1KG`** | Chemical SKU '501-1' omits unit suffix ('KG'), making size ambiguous. |
| `ND-40 Multi Purpose Lube Spray 50ml` | `ND40-50` | brand_hyphenation | **`ND-40-50`** | Brand hyphen omitted in SKU ('ND40-' vs 'ND-40-'). |

---

## 4. Group Assignment & Categorization Issues

| Item Name | SKU | Current Group | Issue | Recommended Target Group |
| :--- | :--- | :--- | :--- | :--- |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | `Solvent Others` | Item in catch-all group 'Solvent Others'; belongs in 'UPVC Solvent'. | **`UPVC Solvent`** |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | *None (unassigned)* | Item has no Zoho item group assigned. | **`Neoseal General`** |
| `Solvent Rate Difference` | `Neoseal CN` | *None (unassigned)* | Item has no Zoho item group assigned. | **`Neoseal Adjustment`** |

---

## 5. Price List Verification

No price-list differences found (or no price list was supplied).

---

## 6. Margin Analysis

| Item Name | SKU | Issue | Recommendation |
| :--- | :--- | :--- | :--- |
| `1 1/4" PVC Ball Valve GS PLUS` | `1.25-PVC-GSP` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `1" UPVC Ball Valve GS` | `1-UPVC-GS` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `200 UPVC Solution 100ml Blue (PVC Can)` | `200-100-UPVC-BLU-CAN` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `200 UPVC Solution 100ml Blue (Tin)` | `200-100-UPVC-BLU-TIN` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `PTFE Tape Premium 12mm 10mtr Yellow` | `10M-YELLOW-12MM` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `PVC Insulation Tape 6mtr (BLUE)` | `6M-INSULATION-BLUE` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `501 SBR Latex 1kg` | `501-1` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `ND-40 Multi Purpose Lube Spray 50ml` | `ND40-50` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |
| `Solvent Rate Difference` | `Neoseal CN` | Purchase rate is missing or non-positive; margin cannot be calculated. | **Set the current purchase rate.** |

---

## 7. Pack Size & MRP

| Item Name | SKU | Issue | Recommendation |
| :--- | :--- | :--- | :--- |
| `1 1/4" PVC Ball Valve GS PLUS` | `1.25-PVC-GSP` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `1 1/4" PVC Ball Valve GS PLUS` | `1.25-PVC-GSP` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `1" UPVC Ball Valve GS` | `1-UPVC-GS` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `1" UPVC Ball Valve GS` | `1-UPVC-GS` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `200 UPVC Solution 100ml Blue (PVC Can)` | `200-100-UPVC-BLU-CAN` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `200 UPVC Solution 100ml Blue (PVC Can)` | `200-100-UPVC-BLU-CAN` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `200 UPVC Solution 100ml Blue (Tin)` | `200-100-UPVC-BLU-TIN` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `200 UPVC Solution 100ml Blue (Tin)` | `200-100-UPVC-BLU-TIN` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `PTFE Tape Premium 12mm 10mtr Yellow` | `10M-YELLOW-12MM` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `PTFE Tape Premium 12mm 10mtr Yellow` | `10M-YELLOW-12MM` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `PVC Insulation Tape 6mtr (BLUE)` | `6M-INSULATION-BLUE` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `PVC Insulation Tape 6mtr (BLUE)` | `6M-INSULATION-BLUE` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `501 SBR Latex 1kg` | `501-1` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `501 SBR Latex 1kg` | `501-1` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `ND-40 Multi Purpose Lube Spray 50ml` | `ND40-50` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `ND-40 Multi Purpose Lube Spray 50ml` | `ND40-50` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |
| `Solvent Rate Difference` | `Neoseal CN` | Pack size is missing or non-positive. | **Set the item pack size to a positive number.** |
| `Solvent Rate Difference` | `Neoseal CN` | MRP is missing or non-positive. | **Set the item MRP to a positive amount.** |

---

## 8. Vendor Alias Configuration

| Item Name | SKU | Issue | Recommendation |
| :--- | :--- | :--- | :--- |
| `1 1/4" PVC Ball Valve GS PLUS` | `1.25-PVC-GSP` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `1" UPVC Ball Valve GS` | `1-UPVC-GS` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `200 UPVC Solution 100ml Blue (PVC Can)` | `200-100-UPVC-BLU-CAN` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `200 UPVC Solution 100ml Blue (Tin)` | `200-100-UPVC-BLU-TIN` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `PVC-UPVC Solution 20ml (Tube)` | `20-PVC-UPVC-CLR-TUBE` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `PTFE Tape Premium 12mm 10mtr` | `10mtr tape` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `PTFE Tape Premium 12mm 10mtr Yellow` | `10M-YELLOW-12MM` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `PVC Insulation Tape 6mtr (BLUE)` | `6M-INSULATION-BLUE` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `501 SBR Latex 1kg` | `501-1` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `ND-40 Multi Purpose Lube Spray 50ml` | `ND40-50` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |
| `Solvent Rate Difference` | `Neoseal CN` | Vendor alias name is not configured. | **Set the Neoseal vendor alias name.** |

---

## Action Checklist

- [ ] Replace `GS PLUS` with `GS Plus` across all 7 PVC Ball Valves.
- [ ] Update `PTFE Tape Premium 12mm 5mtr Yellow` (`5M-YELLOW-12MM`) to White (`5M-WHITE-12MM`).
- [ ] Standardize Insulation Tape parentheses casing to Title Case (e.g. `(Blue)`, `(Green)`, `(Red)`).
- [ ] Re-index SKU `20-PVC-UPVC-CLR-TUBE` to `UPVC-20-CLR-TUBE` and reassign from `Solvent Others` to `UPVC Solvent`.
- [ ] Assign unassigned accounting helper `Solvent Rate Difference` (`Neoseal CN`) to `Neoseal Adjustment`.
- [ ] Append explicit unit suffixes to chemical SKUs (`501-1KG`, `514-10KG`, `507-10L`, `IWP-500-1L`, `518-300G`).
