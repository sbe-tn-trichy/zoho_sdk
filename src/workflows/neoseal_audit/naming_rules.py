"""Domain transformation rules for Neoseal item naming and SKU standardization.

Applies:
1. Title Case 'GS Plus' on all Ball Valves (replacing all-caps 'GS PLUS').
2. 'Solvent Cement' across all solvent solutions (replacing 'Solution').
3. International System of Units (SI) standardization:
   - Space between numerical values and unit symbols (100 ml, 1 kg, 500 g, 10 m, 12 mm, 20 L).
   - Standard SI unit symbols ('m' instead of 'mtr'/'meter').
4. PTFE Tape physical color correction:
   - 5M-YELLOW-12MM is physically White -> 'PTFE Tape Premium 12 mm 5 m White', SKU: '5M-WHITE-12MM'.
5. Silicone Sealant SKU 3-letter color suffix:
   - 701-260-C -> 701-260-CLR (standardized alongside 701-260-BLK and 701-260-WHT).
   - Standardize all-caps names on new master silicone sealant records.
6. Flags zero-stock duplicates:
   - 701-260-B (Stock 0) duplicate of 701-260-BLK.
   - 701-260-W (Stock 0) duplicate of 701-260-WHT.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional


KNOWN_SKU_OVERRIDES: Dict[str, str] = {
    # 5M PTFE tape is physically white
    "5M-YELLOW-12MM": "5M-WHITE-12MM",
    # 701 Silicone clear 3-letter color code
    "701-260-C": "701-260-CLR",
}

KNOWN_DUPLICATE_MAP: Dict[str, Dict[str, str]] = {
    "701-260-B": {
        "master_sku": "701-260-BLK",
        "master_id": "1094368000059488298",
        "reason": "Zero-stock duplicate of active 701-260-BLK with 62 stock",
    },
    "701-260-W": {
        "master_sku": "701-260-WHT",
        "master_id": "1094368000059471316",
        "reason": "Zero-stock duplicate of active 701-260-WHT with 42 stock",
    },
    "105-500-PVC-CLR-TIN": {
        "master_sku": "105-500-PVC-TIN",
        "master_id": "1094368000059821380",
        "reason": "Zero-stock duplicate of active 105-500-PVC-TIN with 35 stock",
    },
}


def standardize_item_name(name: str) -> str:
    """Return the SI-compliant, standardized Neoseal item name."""
    res = str(name or "").strip()

    # 1. GS PLUS -> GS Plus
    if "GS PLUS" in res:
        res = res.replace("GS PLUS", "GS Plus")

    # 2. Solution -> Solvent Cement
    if re.search(r"solution", res, flags=re.IGNORECASE):
        res = re.sub(r"solution", "Solvent Cement", res, flags=re.IGNORECASE)

    # 3. Clean all-caps NEOSEAL prefixes on silicone sealants
    if res.startswith("NEOSEAL 701 GP SILICONE SEALANT"):
        res = re.sub(r"^NEOSEAL 701 GP SILICONE SEALANT", "701 GP Silicone Sealant", res, flags=re.IGNORECASE)
        res = re.sub(r"\bBLACK\b", "Black", res)
        res = re.sub(r"\bWHITE\b", "White", res)
        res = re.sub(r"\bCLEAR\b", "Clear", res)
    if res.startswith("NEOSEAL 105 PVC SOLVENT CEMENT - 500ML TIN CAN"):
        res = "105 PVC Solvent Cement 500 ml (Tin)"

    # 4. Color corrections
    # 5M PTFE Tape is White, not Yellow
    if "PTFE Tape" in res and ("5mtr" in res or "5 m" in res):
        res = re.sub(r"\(Yellow\)", "(White)", res)
        res = re.sub(r"\bYellow\b", "White", res)

    # 5. SI Length Units: mtr -> m, mm spacing
    res = re.sub(r"(\d+)\s*(?:mtr|meter)\b", r"\1 m", res, flags=re.IGNORECASE)
    res = re.sub(r"(\d+)\s*mm\b", r"\1 mm", res, flags=re.IGNORECASE)

    # 6. SI Volume Units: ml, L
    res = re.sub(r"(\d+)\s*ml\b", r"\1 ml", res, flags=re.IGNORECASE)
    res = re.sub(r"(\d+)\s*L\b", r"\1 L", res, flags=re.IGNORECASE)

    # 7. SI Mass Units: kg, g
    res = re.sub(r"(\d+)\s*kg\b", r"\1 kg", res, flags=re.IGNORECASE)
    res = re.sub(r"\b(\d+)\s*g\b", r"\1 g", res, flags=re.IGNORECASE)

    # 8. Title Case parenthetical colors on insulation tapes: (BLUE) -> (Blue)
    res = re.sub(
        r"\((BLUE|GREEN|RED|YELLOW|BLACK|WHITE|CLEAR)\)",
        lambda m: f"({m.group(1).capitalize()})",
        res,
        flags=re.IGNORECASE,
    )

    # Clean redundant multi-spaces
    res = re.sub(r"\s+", " ", res).strip()
    return res


def compute_item_update(item: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Inspect an item and compute standardized name, SKU, and duplicate status."""
    item_id = str(item.get("item_id") or "").strip()
    curr_name = str(item.get("name") or "").strip()
    curr_sku = str(item.get("sku") or "").strip()
    stock = float(item.get("stock_on_hand") or item.get("stock") or 0.0)

    proposed_name = standardize_item_name(curr_name)
    proposed_sku = KNOWN_SKU_OVERRIDES.get(curr_sku, curr_sku)

    # If this is the zero-stock legacy 105-500 tin, avoid duplicate name collision with 105-500-PVC-TIN
    if curr_sku == "105-500-PVC-CLR-TIN" and "(Legacy)" not in curr_name:
        proposed_name = f"{proposed_name} (Legacy)"

    is_duplicate = curr_sku in KNOWN_DUPLICATE_MAP
    dup_meta = KNOWN_DUPLICATE_MAP.get(curr_sku)

    reasons: List[str] = []
    if proposed_name != curr_name:
        reasons.append(f"Name standardized: '{curr_name}' -> '{proposed_name}'")
    if proposed_sku != curr_sku:
        reasons.append(f"SKU updated: '{curr_sku}' -> '{proposed_sku}'")
    if is_duplicate and dup_meta:
        reasons.append(dup_meta["reason"])

    if not reasons:
        return None

    return {
        "item_id": item_id,
        "current_name": curr_name,
        "proposed_name": proposed_name,
        "current_sku": curr_sku,
        "proposed_sku": proposed_sku,
        "stock": stock,
        "name_changed": proposed_name != curr_name,
        "sku_changed": proposed_sku != curr_sku,
        "is_duplicate": is_duplicate,
        "duplicate_info": dup_meta,
        "reasons": reasons,
    }
