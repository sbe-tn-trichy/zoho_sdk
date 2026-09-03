# Neoseal Inventory Item Audit & Nomenclature Report

- **Audited At:** 2026-09-03 18:21:39 UTC
- **Data Source:** Local CSV (items.csv)
- **Total Items:** 1 (Active: 1, Inactive: 0)

---

## Executive Summary

| Audit Check | Status | Issues Found | Focus / Recommendation |
| :--- | :---: | :---: | :--- |
| **1. Duplicates & Twins** | ✅ Clean | 0 | Flagged packaging twins (Tin vs Can) & legacy duplicates |
| **2. Naming Nomenclature** | ✅ Clean | 0 | Standardize Title Case (`GS Plus`, parenthetical tape colors) |
| **3. User-Generated SKUs** | ✅ Clean | 0 | Solvent structure inversion & missing chemical unit suffixes |
| **4. Group Categorization** | ⚠️ Warning | 1 | Unassigned Zoho item groups & catch-all buckets |
| **5. Price List** | ✅ Clean | 0 | Books selling price must match the supplied price list |
| **6. Margin** | ✅ Clean | 0 | Positive margin requires selling price above purchase rate |
| **7. Pack Size & MRP** | ✅ Clean | 0 | Pack size and MRP must be positive values |
| **8. Vendor Alias** | ✅ Clean | 0 | Each item needs its Neoseal vendor alias |

---

## 1. Duplicates & Twin Variants

No duplicate items or high-risk twin variants detected.

---

## 2. Item Naming Nomenclature Issues

All item names follow standard naming conventions.

---

## 3. User-Generated SKU Nomenclature Issues

All user-generated SKUs follow standard formula conventions.

---

## 4. Group Assignment & Categorization Issues

| Item Name | SKU | Current Group | Issue | Recommended Target Group |
| :--- | :--- | :--- | :--- | :--- |
| `Neoseal Item` | `NEO-1` | *None (unassigned)* | Item has no Zoho item group assigned. | **`Neoseal General`** |

---

## 5. Price List Verification

No price-list differences found (or no price list was supplied).

---

## 6. Margin Analysis

All items have a positive calculated margin.

---

## 7. Pack Size & MRP

All items have a positive pack size and MRP.

---

## 8. Vendor Alias Configuration

All items have a vendor alias name.

---

## Action Checklist

- [ ] Replace `GS PLUS` with `GS Plus` across all 7 PVC Ball Valves.
- [ ] Update `PTFE Tape Premium 12mm 5mtr Yellow` (`5M-YELLOW-12MM`) to White (`5M-WHITE-12MM`).
- [ ] Standardize Insulation Tape parentheses casing to Title Case (e.g. `(Blue)`, `(Green)`, `(Red)`).
- [ ] Re-index SKU `20-PVC-UPVC-CLR-TUBE` to `UPVC-20-CLR-TUBE` and reassign from `Solvent Others` to `UPVC Solvent`.
- [ ] Assign unassigned accounting helper `Solvent Rate Difference` (`Neoseal CN`) to `Neoseal Adjustment`.
- [ ] Append explicit unit suffixes to chemical SKUs (`501-1KG`, `514-10KG`, `507-10L`, `IWP-500-1L`, `518-300G`).
