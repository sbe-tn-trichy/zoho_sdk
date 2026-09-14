"""Read-only, purchase-account-scoped Neoseal stock-count preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from zoho.inventory import ZohoInventoryAPI
from workflows.core.matching import to_decimal, to_text


@dataclass(frozen=True)
class CountPlacement:
    group: str
    subgroup: str
    group_order: int = 90
    subgroup_order: int = 90
    item_order: int = 0

    def __post_init__(self) -> None:
        if not self.group.strip() or not self.subgroup.strip():
            raise ValueError("Layout group and subgroup must be non-empty.")
        for value in (self.group_order, self.subgroup_order, self.item_order):
            if type(value) is not int or value < 0:
                raise ValueError("Layout orders must be non-negative integers.")


@dataclass(frozen=True)
class StockCountRow:
    sort_order: int
    placement: CountPlacement
    item_id: str
    sku: str
    name: str
    unit: str
    status: str
    source_group: str
    available_quantity: Decimal | None
    stock_on_hand: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StockCount:
    purchase_account_id: str
    location_id: str | None
    generated_at: str
    rows: tuple[StockCountRow, ...]


@dataclass(frozen=True)
class SKUMappingRow:
    sku: str
    cell: str
    item_id: str
    name: str
    stock_on_hand_cell: str | None = None


def format_cell_address(row: int, col: int) -> str:
    """Convert 1-based (row, col) to standard A1 notation, e.g. (4, 2) -> 'B4'."""
    if row < 1 or col < 1:
        raise ValueError("Row and column must be positive integers (1-based).")
    col_str = ""
    c = col
    while c > 0:
        c, remainder = divmod(c - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row}"


def parse_cell_address(cell: str) -> tuple[int, int]:
    """Parse standard A1 notation into 1-based (row, col), e.g. 'B4' -> (4, 2)."""
    cell_str = cell.strip().upper()
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_str)
    if not match:
        raise ValueError(f"Invalid cell address: {cell!r}.")
    col_letters, row_str = match.groups()
    row = int(row_str)
    if row < 1:
        raise ValueError(f"Invalid row number in cell address: {cell!r}.")
    col = 0
    for ch in col_letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return row, col


def default_placement(item: Mapping[str, Any]) -> CountPlacement:
    """Suggest count sections without changing the remote item groups."""
    name = to_text(item.get("name"))
    text = " ".join((name, to_text(item.get("sku")), to_text(item.get("group_name")))).lower()
    if "rate difference" in text or "neoseal cn" in text:
        return CountPlacement("Adjustments", "Accounting items", 99, 0)
    if re.search(r"solvent|solution", text):
        material = next((m for m in ("CPVC", "UPVC", "PVC") if m.lower() in text), "Other solvents")
        grade = re.match(r"(?:neoseal\s+)?(\d{3})\b", name, re.I)
        subgroup = material + (f" / Grade {grade[1]}" if grade else "")
        return CountPlacement("Solvent cement", subgroup, 10, {"PVC": 10, "CPVC": 20, "UPVC": 30}.get(material, 90))
    if "ball valve" in text:
        handle = "GS Plus" if re.search(r"gs\s*plus|gsp", text) else "MS" if re.search(r"\bms\b", text) else "Other handles"
        return CountPlacement("Ball valves", handle, 20, {"GS Plus": 10, "MS": 20}.get(handle, 90))
    if "tape" in text:
        kind = "PTFE" if "ptfe" in text else "Insulation" if "insulation" in text else "Other tapes"
        return CountPlacement("Tapes", kind, 30, {"PTFE": 10, "Insulation": 20}.get(kind, 90))
    if "silicone" in text or "sealant" in text:
        return CountPlacement("Sealants", "Silicone" if "silicone" in text else "Other sealants", 40, 10)
    if re.search(r"latex|crack|terrace|waterproof|tile|grout|coat", text):
        family = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b.*$", "", name, flags=re.I)
        return CountPlacement("Construction chemicals", family or "Other chemicals", 50, 10)
    if re.search(r"nd-?40|lubricant|cleaner|maintenance", text):
        return CountPlacement("Maintenance", "Cleaners and lubricants", 60, 10)
    return CountPlacement("Other items", to_text(item.get("group_name")) or "Unclassified", 90, 90)


def _natural(value: str) -> tuple:
    return tuple((1, Decimal(part)) if re.fullmatch(r"\d+(?:\.\d+)?", part) else (0, part.casefold())
                 for part in re.split(r"(\d+(?:\.\d+)?)", value))


def _quantity(value: Any) -> Decimal | None:
    result = to_decimal(value)
    return result if result is not None and result.is_finite() else None


def build_stock_count(
    items: Sequence[Mapping[str, Any]],
    *,
    purchase_account_id: str,
    location_id: str | None = None,
    layout: Mapping[str, CountPlacement] | None = None,
) -> StockCount:
    """Build one row per item; missing balances stay unknown, never zero."""
    account = purchase_account_id.strip()
    if not account:
        raise ValueError("purchase_account_id is required.")
    if location_id is not None and not location_id.strip():
        raise ValueError("location_id cannot be blank.")
    location_id = location_id.strip() if location_id else None
    layout = layout or {}
    rows = []
    seen = set()
    group_orders: dict[str, int] = {}
    subgroup_orders: dict[tuple[str, str], int] = {}
    # Explicit layout ranks apply to the whole group, including inferred rows.
    for placement in layout.values():
        for key, rank, ranks in ((placement.group, placement.group_order, group_orders),
                                 ((placement.group, placement.subgroup), placement.subgroup_order, subgroup_orders)):
            if key in ranks and ranks[key] != rank:
                raise ValueError(f"Conflicting layout orders for {key!r}.")
            ranks[key] = rank
    for item in items:
        item_id = to_text(item.get("item_id"))
        if not item_id or item_id in seen:
            raise ValueError(f"Missing or duplicate item_id: {item_id!r}.")
        seen.add(item_id)
        if to_text(item.get("purchase_account_id")) != account:
            raise ValueError(f"Item {item_id} does not belong to the requested purchase account.")
        placement = layout.get(item_id) or default_placement(item)
        warnings = []
        if location_id:
            matches = [loc for loc in (item.get("locations") or [])
                       if to_text(loc.get("location_id")) == location_id]
            if len(matches) > 1:
                raise ValueError(f"Duplicate location balance for item {item_id}.")
            balance = matches[0] if matches else {}
            available = _quantity(balance.get("location_available_stock"))
            on_hand = _quantity(balance.get("location_stock_on_hand"))
            if not matches:
                warnings.append("Location balance missing")
        else:
            available = _quantity(item.get("available_stock"))
            on_hand = _quantity(item.get("stock_on_hand"))
        if available is None:
            warnings.append("Available quantity unknown")
        elif available < 0:
            warnings.append("Negative available quantity")
        if on_hand is None:
            warnings.append("Stock on hand unknown")
        elif on_hand < 0:
            warnings.append("Negative stock on hand")
        rows.append(StockCountRow(0, placement, item_id, to_text(item.get("sku")),
                                  to_text(item.get("name")), to_text(item.get("unit")),
                                  to_text(item.get("status")), to_text(item.get("group_name")),
                                  available, on_hand, tuple(warnings)))
    unknown = set(layout) - seen
    if unknown:
        raise ValueError("Layout references items outside this count: " + ", ".join(sorted(unknown)))
    def key(row: StockCountRow) -> tuple:
        p = row.placement
        return (group_orders.get(p.group, p.group_order), _natural(p.group),
                subgroup_orders.get((p.group, p.subgroup), p.subgroup_order), _natural(p.subgroup),
                p.item_order, _natural(row.name), _natural(row.sku), row.item_id)
    ordered = tuple(replace(row, sort_order=i) for i, row in enumerate(sorted(rows, key=key), 1))
    return StockCount(account, location_id, datetime.now(timezone.utc).isoformat(), ordered)


def fetch_neoseal_stock_count(
    inventory_client: ZohoInventoryAPI,
    *,
    purchase_account_id: str,
    location_id: str | None = None,
    status: str = "active",
    layout: Mapping[str, CountPlacement] | None = None,
) -> StockCount:
    """List the scoped catalog, then bulk-read complete Inventory item balances."""
    account = purchase_account_id.strip()
    if not account:
        raise ValueError("purchase_account_id is required.")
    if status != "active":
        raise ValueError("Neoseal stock count supports active items only.")
    catalog = inventory_client.items.list_by_purchase_account(account, status=status)
    ids = [to_text(item.get("item_id")) for item in catalog]
    if len(ids) != len(set(ids)) or any(not value.isdigit() for value in ids):
        raise ValueError("Catalog contains missing, invalid, or duplicate item IDs.")
    details = inventory_client.items.get_details(ids) if ids else []
    if len(details) != len(ids) or {to_text(it.get("item_id")) for it in details} != set(ids):
        raise ValueError("Incomplete or unexpected item details.")
    by_id = {to_text(item.get("item_id")): item for item in catalog}
    merged = [{**by_id[to_text(item.get("item_id"))], **item} for item in details]
    return build_stock_count(merged, purchase_account_id=account, location_id=location_id, layout=layout)
