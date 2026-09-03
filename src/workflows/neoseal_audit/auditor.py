"""Pure domain audit logic for Neoseal inventory items."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Sequence, TypedDict


class DuplicateMatch(TypedDict):
    match_type: str  # "legacy_duplicate", "packaging_twin", "near_duplicate"
    similarity: float
    item_a: Dict[str, Any]
    item_b: Dict[str, Any]
    details: str


class NomenclatureIssue(TypedDict):
    item_id: str
    name: str
    sku: str
    issue_type: str
    severity: str  # "warning", "info"
    description: str
    recommendation: str


class GroupCategorizationIssue(TypedDict):
    item_id: str
    name: str
    sku: str
    current_group: str
    issue_type: str  # "missing_group", "catchall_group"
    recommended_group: str
    description: str


class ItemDataIssue(TypedDict):
    item_id: str
    name: str
    sku: str
    issue_type: str
    severity: str
    description: str
    recommendation: str


class PriceListIssue(TypedDict):
    item_id: str
    name: str
    sku: str
    system_price: float
    price_list_price: float | None
    issue_type: str  # "missing_price_list_entry", "price_mismatch"
    description: str


class NeosealAuditResult(TypedDict):
    total_audited: int
    active_count: int
    inactive_count: int
    duplicates: List[DuplicateMatch]
    naming_issues: List[NomenclatureIssue]
    sku_issues: List[NomenclatureIssue]
    group_issues: List[GroupCategorizationIssue]
    price_list_issues: List[PriceListIssue]
    margin_issues: List[ItemDataIssue]
    pack_mrp_issues: List[ItemDataIssue]
    alias_issues: List[ItemDataIssue]


class NeosealItemAuditor:
    """Audits Neoseal catalog quality, pricing, margins, and vendor metadata."""

    def __init__(
        self,
        items: Sequence[Mapping[str, Any]],
        price_list: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.raw_items = [self._normalize_item(it) for it in items]
        self.price_list = (
            self._normalize_price_list(price_list) if price_list is not None else None
        )

    @staticmethod
    def _normalize_item(raw: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "item_id": str(raw.get("item_id") or "").strip(),
            "name": str(raw.get("name") or "").strip(),
            "sku": str(raw.get("sku") or "").strip(),
            "status": str(raw.get("status") or "active").strip().lower(),
            "group_id": str(raw.get("group_id") or "").strip() if raw.get("group_id") is not None else "",
            "group_name": str(raw.get("group_name") or "").strip() if raw.get("group_name") is not None and str(raw.get("group_name")).lower() != "nan" else "",
            "stock_on_hand": float(raw.get("stock_on_hand") or 0.0) if raw.get("stock_on_hand") is not None and str(raw.get("stock_on_hand")).lower() != "nan" else 0.0,
            "rate": float(raw.get("rate") or 0.0) if raw.get("rate") is not None and str(raw.get("rate")).lower() != "nan" else 0.0,
            "purchase_rate": NeosealItemAuditor._as_float(raw.get("purchase_rate")),
            "pack_size": NeosealItemAuditor._as_float(raw.get("pack_size")),
            "mrp": NeosealItemAuditor._as_float(raw.get("mrp")),
            "alias_name": str(raw.get("alias_name") or "").strip(),
        }

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None or str(value).strip().lower() in {"", "nan", "none"}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_price_list(
        price_list: Sequence[Mapping[str, Any]],
    ) -> Dict[str, float | None]:
        """Return price-list prices by normalized SKU.

        Price-list exports must provide ``sku`` plus one of ``price``, ``rate``,
        or ``selling_price``. Duplicate SKUs are rejected because their expected
        selling price is ambiguous.
        """
        prices: Dict[str, float | None] = {}
        for row in price_list:
            sku = str(row.get("sku") or "").strip().casefold()
            if not sku:
                continue
            if sku in prices:
                raise ValueError(f"Price list contains duplicate SKU {sku!r}.")
            price = next(
                (row.get(field) for field in ("price", "rate", "selling_price") if field in row),
                None,
            )
            prices[sku] = NeosealItemAuditor._as_float(price)
        return prices

    def find_duplicates(self) -> List[DuplicateMatch]:
        """Detect duplicates, near-duplicates, inactive legacy pairs, and container twins."""
        results: List[DuplicateMatch] = []
        n = len(self.raw_items)

        for i in range(n):
            for j in range(i + 1, n):
                a = self.raw_items[i]
                b = self.raw_items[j]

                name_a = a["name"].lower()
                name_b = b["name"].lower()

                # Clean strings for sequence matching
                clean_a = re.sub(r"[^a-z0-9]", "", name_a)
                clean_b = re.sub(r"[^a-z0-9]", "", name_b)

                if not clean_a or not clean_b:
                    continue

                similarity = SequenceMatcher(None, clean_a, clean_b).ratio()

                # 1. Check for packaging twins (e.g. Tin vs PVC Can)
                is_twin = False
                if ("(tin)" in name_a and "(pvc can)" in name_b) or ("(pvc can)" in name_a and "(tin)" in name_b):
                    base_a = re.sub(r"\((tin|pvc can)\)", "", name_a).strip()
                    base_b = re.sub(r"\((tin|pvc can)\)", "", name_b).strip()
                    if base_a == base_b:
                        is_twin = True
                        results.append({
                            "match_type": "packaging_twin",
                            "similarity": 0.98,
                            "item_a": a,
                            "item_b": b,
                            "details": (
                                "Packaging twin (Tin vs PVC Can). Identical formulation and volume; "
                                "high risk of stock mismatch and negative billing entries."
                            ),
                        })

                # 2. Check for active vs inactive legacy duplicate
                if not is_twin and (a["status"] != b["status"]):
                    if similarity >= 0.80 or clean_a in clean_b or clean_b in clean_a:
                        results.append({
                            "match_type": "legacy_duplicate",
                            "similarity": round(similarity, 3),
                            "item_a": a,
                            "item_b": b,
                            "details": (
                                f"Legacy duplicate pair: '{a['name']}' [{a['status']}] vs "
                                f"'{b['name']}' [{b['status']}]."
                            ),
                        })
                        continue

                # 3. Near-duplicate active items (different SKU, similarity >= 0.85)
                if not is_twin and a["sku"] != b["sku"] and similarity >= 0.85:
                    # Exclude known distinct size/color variants
                    if self._is_distinct_variant(a["name"], b["name"]):
                        continue
                    results.append({
                        "match_type": "near_duplicate",
                        "similarity": round(similarity, 3),
                        "item_a": a,
                        "item_b": b,
                        "details": f"High name similarity ({similarity:.1%}) with distinct SKUs.",
                    })

        return results

    @staticmethod
    def _is_distinct_variant(name_a: str, name_b: str) -> bool:
        """Return True if items are known valid dimension/color variants."""
        # Different sizes (e.g. 5mtr vs 10mtr, 50ml vs 100ml, 3/4" vs 1")
        sizes_a = set(re.findall(r"\b\d+(?:\.\d+)?(?:mm|mtr|ml|l|kg|g)?\b", name_a.lower()))
        sizes_b = set(re.findall(r"\b\d+(?:\.\d+)?(?:mm|mtr|ml|l|kg|g)?\b", name_b.lower()))
        if sizes_a != sizes_b:
            return True

        # Different colors
        colors = {"blue", "black", "red", "yellow", "green", "white", "clear"}
        col_a = set(name_a.lower().split()).intersection(colors)
        col_b = set(name_b.lower().split()).intersection(colors)
        if col_a and col_b and col_a != col_b:
            return True

        # Handle types (GS vs MS)
        if ("gs" in name_a.lower() and "ms" in name_b.lower()) or ("ms" in name_a.lower() and "gs" in name_b.lower()):
            return True

        return False

    def check_naming_nomenclature(self) -> List[NomenclatureIssue]:
        """Audit item names for nomenclature compliance."""
        issues: List[NomenclatureIssue] = []

        for it in self.raw_items:
            name = it["name"]
            sku = it["sku"]
            item_id = it["item_id"]

            # Ball Valves
            if "ball valve" in name.lower():
                if "GS PLUS" in name:
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "casing_convention",
                        "severity": "info",
                        "description": "Uses uppercase 'GS PLUS' instead of Title Case 'GS Plus'.",
                        "recommendation": name.replace("GS PLUS", "GS Plus"),
                    })

            # Tapes
            if "insulation tape" in name.lower():
                # Check color parenthesis casing e.g. (BLUE)
                m = re.search(r"\(([A-Z]+)\)", name)
                if m and m.group(1) not in ["PVC", "UPVC", "CPVC", "BLOCK"]:
                    color = m.group(1)
                    title_color = color.title()
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "casing_convention",
                        "severity": "info",
                        "description": f"Parenthetical color '({color})' is all-caps.",
                        "recommendation": name.replace(f"({color})", f"({title_color})"),
                    })

            # Chemicals spacing
            if re.search(r"\b(\d+)\s*L\b", name):
                m_chem = re.search(r"\b(\d+)(L)\b", name)
                if m_chem:
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "spacing_convention",
                        "severity": "info",
                        "description": f"Volume unit lacks space ('{m_chem.group(0)}').",
                        "recommendation": name.replace(m_chem.group(0), f"{m_chem.group(1)} L"),
                    })

        return issues

    def check_sku_nomenclature(self) -> List[NomenclatureIssue]:
        """Audit user-generated SKUs for structural formula adherence."""
        issues: List[NomenclatureIssue] = []

        for it in self.raw_items:
            name = it["name"]
            sku = it["sku"]
            item_id = it["item_id"]
            grp = it["group_name"]

            # Skip accounting helpers
            if sku == "Neoseal CN" or "Rate Difference" in name:
                continue

            # 1. Solvents: [Grade]-[Size]-[Material]-[Color]-[Container]
            if "solution" in name.lower() or "solvent" in name.lower() or "solvent" in grp.lower():
                parts = sku.split("-")
                # Specific anomaly: 20-PVC-UPVC-CLR-TUBE
                if sku == "20-PVC-UPVC-CLR-TUBE":
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "inverted_sku_structure",
                        "severity": "warning",
                        "description": "SKU starts with package size ('20') instead of product type/grade.",
                        "recommendation": "UPVC-20-CLR-TUBE",
                    })
                elif len(parts) < 5:
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "incomplete_solvent_sku",
                        "severity": "warning",
                        "description": f"Solvent SKU has {len(parts)} segments; expected 5 (Grade-Size-Material-Color-Container).",
                        "recommendation": "Follow [Grade]-[Size]-[Material]-[Color]-[Container] pattern.",
                    })

            # 2. Ball Valves: [DecimalSize]-[Material]-[Handle]
            elif "ball valve" in name.lower() or "ball valve" in grp.lower():
                parts = sku.split("-")
                if len(parts) != 3:
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "irregular_ball_valve_sku",
                        "severity": "warning",
                        "description": f"Ball Valve SKU '{sku}' does not match [DecimalSize]-[Material]-[Handle].",
                        "recommendation": "Standardize to [Size]-[Material]-[Handle] (e.g. 0.75-PVC-GSP).",
                    })

            # 3. PTFE Tapes: [Length]M-[COLOR]-[WIDTH]
            elif "ptfe" in name.lower():
                if it["status"] == "inactive" and sku == "10mtr tape":
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "legacy_sku_format",
                        "severity": "warning",
                        "description": "Legacy unstandardized tape SKU '10mtr tape'.",
                        "recommendation": "10M-WHITE-12MM",
                    })
                elif not re.match(r"^\d+M-[A-Z]+-\d+MM(?:-[\d\.]+)?$", sku):
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "irregular_tape_sku",
                        "severity": "warning",
                        "description": f"PTFE tape SKU '{sku}' does not match standard [Length]M-[COLOR]-[WIDTH].",
                        "recommendation": "Follow [Length]M-[COLOR]-[WIDTH] (e.g. 10M-WHITE-12MM).",
                    })

            # 4. Chemicals & Waterproofing: Missing explicit unit in SKU
            chemical_groups = {
                "bitucoat", "crack filler", "damp kill", "eco prime", "iwp 500",
                "neocem", "quick leak stop", "sbr latex", "seal x", "terrace coat", "sr 609"
            }
            if grp.lower() in chemical_groups or any(g in name.lower() for g in ["bitucoat", "crack filler", "damp kill", "eco prime", "iwp 500", "sbr latex"]):
                parts = sku.split("-")
                last_part = parts[-1].upper()
                has_unit = any(u in last_part for u in ["KG", "L", "G", "ML"])
                
                # Check if name has a weight/volume unit
                m_unit = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|l|g|ml)\b", name, re.IGNORECASE)
                if m_unit and not has_unit:
                    num_val, unit_val = m_unit.group(1), m_unit.group(2).upper()
                    # e.g. 501-1 -> 501-1KG
                    rec_sku = f"{parts[0]}-{num_val}{unit_val}"
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "missing_unit_suffix",
                        "severity": "info",
                        "description": f"Chemical SKU '{sku}' omits unit suffix ('{unit_val}'), making size ambiguous.",
                        "recommendation": rec_sku,
                    })

            # 5. ND-40 Lubricant spray hyphenation
            if "nd-40" in name.lower() or "nd40" in name.lower():
                if sku.startswith("ND40-"):
                    issues.append({
                        "item_id": item_id,
                        "name": name,
                        "sku": sku,
                        "issue_type": "brand_hyphenation",
                        "severity": "info",
                        "description": "Brand hyphen omitted in SKU ('ND40-' vs 'ND-40-').",
                        "recommendation": sku.replace("ND40-", "ND-40-"),
                    })

        return issues

    def check_group_categorization(self) -> List[GroupCategorizationIssue]:
        """Audit items for unassigned groups or catch-all bucket assignments."""
        issues: List[GroupCategorizationIssue] = []

        for it in self.raw_items:
            grp = it["group_name"]
            name = it["name"]
            sku = it["sku"]
            item_id = it["item_id"]

            # 1. Missing / unassigned group
            if not grp:
                rec_group = "Neoseal Adjustment" if "rate difference" in name.lower() else "Neoseal General"
                issues.append({
                    "item_id": item_id,
                    "name": name,
                    "sku": sku,
                    "current_group": "",
                    "issue_type": "missing_group",
                    "recommended_group": rec_group,
                    "description": "Item has no Zoho item group assigned.",
                })

            # 2. Misgrouped solvent: Solvent Others
            elif grp == "Solvent Others":
                rec = "UPVC Solvent" if "upvc" in name.lower() else "PVC Solvent"
                issues.append({
                    "item_id": item_id,
                    "name": name,
                    "sku": sku,
                    "current_group": grp,
                    "issue_type": "catchall_group",
                    "recommended_group": rec,
                    "description": f"Item in catch-all group '{grp}'; belongs in '{rec}'.",
                })

            # 3. Neoseal Others
            elif grp == "Neoseal Others":
                issues.append({
                    "item_id": item_id,
                    "name": name,
                    "sku": sku,
                    "current_group": grp,
                    "issue_type": "catchall_group",
                    "recommended_group": "Neoseal Maintenance",
                    "description": "Item placed in generic catch-all bucket 'Neoseal Others'.",
                })

        return issues

    def check_price_list(self) -> List[PriceListIssue]:
        """Compare each Neoseal item selling price with the supplied price list.

        An empty price list means the comparison was not requested, so no issues
        are produced. When a price list is supplied, every item with a SKU must
        have one matching entry and its listed price must equal Books ``rate``.
        """
        if self.price_list is None:
            return []

        issues: List[PriceListIssue] = []
        for it in self.raw_items:
            sku_key = it["sku"].casefold()
            if not sku_key:
                issues.append({
                    "item_id": it["item_id"],
                    "name": it["name"],
                    "sku": it["sku"],
                    "system_price": it["rate"],
                    "price_list_price": None,
                    "issue_type": "missing_price_list_entry",
                    "description": "Item has no SKU, so it cannot be matched to the price list.",
                })
                continue
            price_list_price = self.price_list.get(sku_key)
            if sku_key not in self.price_list or price_list_price is None:
                issues.append({
                    "item_id": it["item_id"],
                    "name": it["name"],
                    "sku": it["sku"],
                    "system_price": it["rate"],
                    "price_list_price": price_list_price,
                    "issue_type": "missing_price_list_entry",
                    "description": "No usable price-list price was found for this SKU.",
                })
            elif it["rate"] != price_list_price:
                issues.append({
                    "item_id": it["item_id"],
                    "name": it["name"],
                    "sku": it["sku"],
                    "system_price": it["rate"],
                    "price_list_price": price_list_price,
                    "issue_type": "price_mismatch",
                    "description": "Zoho Books selling price does not match the price-list price.",
                })
        return issues

    def check_margin(self) -> List[ItemDataIssue]:
        """Flag items whose selling price does not produce a positive margin."""
        issues: List[ItemDataIssue] = []
        for it in self.raw_items:
            purchase_rate = it["purchase_rate"]
            rate = it["rate"]
            if purchase_rate is None or purchase_rate <= 0:
                issues.append(self._data_issue(
                    it, "missing_purchase_rate", "warning",
                    "Purchase rate is missing or non-positive; margin cannot be calculated.",
                    "Set the current purchase rate.",
                ))
            elif rate <= 0:
                issues.append(self._data_issue(
                    it, "missing_selling_price", "warning",
                    "Selling price is missing or non-positive; margin cannot be calculated.",
                    "Set a positive selling price.",
                ))
            elif rate <= purchase_rate:
                issues.append(self._data_issue(
                    it, "non_positive_margin", "warning",
                    f"Selling price {rate:.2f} is not greater than purchase rate {purchase_rate:.2f}.",
                    "Set a selling price above the purchase rate or verify the cost.",
                ))
        return issues

    def check_pack_size_and_mrp(self) -> List[ItemDataIssue]:
        """Ensure item pack size and MRP are populated with positive values."""
        issues: List[ItemDataIssue] = []
        for it in self.raw_items:
            if it["pack_size"] is None or it["pack_size"] <= 0:
                issues.append(self._data_issue(
                    it, "missing_pack_size", "warning",
                    "Pack size is missing or non-positive.",
                    "Set the item pack size to a positive number.",
                ))
            if it["mrp"] is None or it["mrp"] <= 0:
                issues.append(self._data_issue(
                    it, "missing_mrp", "warning",
                    "MRP is missing or non-positive.",
                    "Set the item MRP to a positive amount.",
                ))
            elif it["mrp"] < it["rate"]:
                issues.append(self._data_issue(
                    it, "mrp_below_selling_price", "warning",
                    f"MRP {it['mrp']:.2f} is lower than selling price {it['rate']:.2f}.",
                    "Set MRP at or above the item selling price, or verify both values.",
                ))
        return issues

    def check_aliases(self) -> List[ItemDataIssue]:
        """Ensure every item carries the vendor-facing alias used by Neoseal."""
        return [
            self._data_issue(
                it, "missing_alias_name", "warning",
                "Vendor alias name is not configured.",
                "Set the Neoseal vendor alias name.",
            )
            for it in self.raw_items
            if not it["alias_name"]
        ]

    @staticmethod
    def _data_issue(
        item: Mapping[str, Any],
        issue_type: str,
        severity: str,
        description: str,
        recommendation: str,
    ) -> ItemDataIssue:
        return {
            "item_id": item["item_id"],
            "name": item["name"],
            "sku": item["sku"],
            "issue_type": issue_type,
            "severity": severity,
            "description": description,
            "recommendation": recommendation,
        }

    def audit(self) -> NeosealAuditResult:
        """Run all audit checks and compile result summary."""
        active = [it for it in self.raw_items if it["status"] == "active"]
        inactive = [it for it in self.raw_items if it["status"] != "active"]

        return {
            "total_audited": len(self.raw_items),
            "active_count": len(active),
            "inactive_count": len(inactive),
            "duplicates": self.find_duplicates(),
            "naming_issues": self.check_naming_nomenclature(),
            "sku_issues": self.check_sku_nomenclature(),
            "group_issues": self.check_group_categorization(),
            "price_list_issues": self.check_price_list(),
            "margin_issues": self.check_margin(),
            "pack_mrp_issues": self.check_pack_size_and_mrp(),
            "alias_issues": self.check_aliases(),
        }


def audit_neoseal_items(
    items: Sequence[Mapping[str, Any]],
    price_list: Sequence[Mapping[str, Any]] | None = None,
) -> NeosealAuditResult:
    """Convenience functional API to run Neoseal item audit."""
    return NeosealItemAuditor(items, price_list=price_list).audit()
