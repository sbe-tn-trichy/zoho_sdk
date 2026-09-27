"""Export Inventory items for a purchase account and flag missing vendor aliases."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


FIELDS = (
    "item_id",
    "name",
    "sku",
    "alias_name",
    "has_alias_name",
    "manufacturer",
    "purchase_account_id",
)


def export_row(item: Mapping[str, Any]) -> Dict[str, str]:
    """Return the stable CSV representation of one Inventory item."""
    alias = str(item.get("alias_name") or "").strip()
    return {
        "item_id": str(item.get("item_id") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "sku": str(item.get("sku") or "").strip(),
        "alias_name": alias,
        "has_alias_name": "true" if alias else "false",
        "manufacturer": str(item.get("manufacturer") or "").strip(),
        "purchase_account_id": str(item.get("purchase_account_id") or "").strip(),
    }


def write_export_rows(path: Path | str, rows: Sequence[Mapping[str, str]]) -> None:
    """Write export rows to CSV."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def export_inventory_items(
    inventory_client: Any,
    purchase_account_id: str,
    *,
    status: str = "active",
    output_path: Path | str = Path("output/neoseal_items.csv"),
    missing_output_path: Path | str = Path("output/neoseal_items_missing_alias.csv"),
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Fetch items by purchase account, export CSV, and write missing aliases."""
    items = inventory_client.items.list_by_purchase_account(
        purchase_account_id,
        status=status,
    )
    rows = [export_row(item) for item in items]
    missing = [row for row in rows if row["has_alias_name"] == "false"]
    write_export_rows(output_path, rows)
    write_export_rows(missing_output_path, missing)
    return rows, missing
