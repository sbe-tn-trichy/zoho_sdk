"""Higher-level helper functions for Zoho Books and Inventory item operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("zoho.helpers.items")


def _get_items_iterable(items_resource: Any, params: Dict[str, Any]) -> Any:
    """Safely obtain iterable over items supporting list_all, list_iter, or list."""
    if hasattr(items_resource, "list_all") and callable(items_resource.list_all):
        res = items_resource.list_all(params=params, resource_key="items")
        if isinstance(res, list):
            return res
    if hasattr(items_resource, "list_iter") and callable(items_resource.list_iter):
        res = items_resource.list_iter(params=params, resource_key="items")
        if isinstance(res, (list, tuple)) or hasattr(res, "__iter__"):
            return res
    if hasattr(items_resource, "list") and callable(items_resource.list):
        res = items_resource.list(params=params)
        if isinstance(res, dict):
            return res.get("items", [])
        if isinstance(res, list):
            return res
    return []


def fetch_items_lookup(
    books_client: Any,
    key_field: str = "name",
    status: str = "active",
    purchase_account_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Fetch all items from Zoho Books/Inventory and index them by `key_field`.

    Supports `name`, `sku`, `item_id`, `item_name`, etc. Optional `purchase_account_id`
    scopes the query to a specific purchase account.
    """
    params: Dict[str, Any] = {"status": status}
    if purchase_account_id:
        params["purchase_account_id"] = str(purchase_account_id).strip()

    lookup: Dict[str, Dict[str, Any]] = {}

    try:
        items = _get_items_iterable(books_client.items, params)
        for item in items:
            key_val = item.get(key_field)
            if key_val is None and key_field == "name":
                key_val = item.get("item_name")
            elif key_val is None and key_field == "item_name":
                key_val = item.get("name")

            if key_val is not None:
                clean_key = str(key_val).strip()
                if clean_key:
                    lookup[clean_key] = item
    except Exception as exc:
        logger.error(f"Failed to fetch and index items by key '{key_field}': {exc}")
        raise

    return lookup


def fetch_items_by_purchase_account(
    books_client: Any,
    purchase_account_id: str,
    key_field: str = "sku",
    status: str = "all",
) -> Dict[str, Dict[str, Any]]:
    """Fetch items scoped to a specific purchase account and index them by `key_field`."""
    account_id = str(purchase_account_id or "").strip()
    if not account_id:
        raise ValueError("purchase_account_id is required.")

    return fetch_items_lookup(
        books_client,
        key_field=key_field,
        status=status,
        purchase_account_id=account_id,
    )


def find_item_by_sku_or_name(
    books_client: Any,
    query: str,
    purchase_account_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Search for an item by matching SKU or name, optionally scoped by purchase_account_id."""
    cleaned = str(query or "").strip()
    if not cleaned:
        return None

    target = cleaned.lower()
    params: Dict[str, Any] = {"search_text": cleaned}
    if purchase_account_id:
        params["purchase_account_id"] = str(purchase_account_id).strip()

    try:
        res = books_client.items.list(params=params)
        items = res.get("items", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
        for item in items:
            sku = str(item.get("sku") or "").strip().lower()
            name = str(item.get("item_name") or item.get("name") or "").strip().lower()
            if target in (sku, name):
                return item

        for item in items:
            name = str(item.get("item_name") or item.get("name") or "").strip().lower()
            if target in name:
                return item
    except Exception as exc:
        logger.warning(f"Error searching items for '{cleaned}': {exc}")

    return None

