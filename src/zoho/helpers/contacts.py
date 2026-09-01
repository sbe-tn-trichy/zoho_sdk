"""Higher-level helper functions for Zoho Books contact operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from .custom_fields import get_custom_field_value

logger = logging.getLogger("zoho.helpers.contacts")


def _get_contacts_iterable(contacts_resource: Any, params: Dict[str, Any]) -> Any:
    """Safely obtain iterable over contacts supporting list_all, list_iter, or list."""
    if hasattr(contacts_resource, "list_all") and callable(contacts_resource.list_all):
        res = contacts_resource.list_all(params=params, resource_key="contacts")
        if isinstance(res, list):
            return res
    if hasattr(contacts_resource, "list_iter") and callable(contacts_resource.list_iter):
        res = contacts_resource.list_iter(params=params, resource_key="contacts")
        if isinstance(res, (list, tuple)) or hasattr(res, "__iter__"):
            return res
    if hasattr(contacts_resource, "list") and callable(contacts_resource.list):
        res = contacts_resource.list(params=params)
        if isinstance(res, dict):
            return res.get("contacts", [])
        if isinstance(res, list):
            return res
    return []


def find_contact_by_gstin(
    books_client: Any,
    gstin: str,
    contact_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up a contact by their GSTIN (tax identifier).

    Performs case-insensitive matching against `gst_no` and custom fields.
    """
    cleaned_gstin = str(gstin or "").strip().upper()
    if not cleaned_gstin:
        return None

    params: Dict[str, Any] = {}
    if contact_type:
        params["contact_type"] = contact_type

    try:
        contacts = _get_contacts_iterable(books_client.contacts, params)
        for contact in contacts:
            c_gst = str(contact.get("gst_no") or contact.get("gstin") or "").strip().upper()
            if c_gst == cleaned_gstin:
                return contact
            # Check custom field if GSTIN stored in custom fields
            cf_gst = get_custom_field_value(contact, "gstin") or get_custom_field_value(contact, "gst_no")
            if cf_gst and str(cf_gst).strip().upper() == cleaned_gstin:
                return contact
    except Exception as exc:
        logger.warning(f"Error querying contacts by GSTIN {cleaned_gstin}: {exc}")
        return None

    return None


def find_contact_by_name(
    books_client: Any,
    contact_name: str,
    contact_type: Optional[str] = None,
    exact: bool = True,
) -> Optional[Dict[str, Any]]:
    """Look up a contact by contact_name or company_name."""
    name_cleaned = str(contact_name or "").strip()
    if not name_cleaned:
        return None

    target = name_cleaned.lower()
    params: Dict[str, Any] = {"contact_name": name_cleaned}
    if contact_type:
        params["contact_type"] = contact_type

    try:
        res = books_client.contacts.list(params=params)
        contacts = res.get("contacts", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
        for contact in contacts:
            c_name = str(contact.get("contact_name") or "").strip().lower()
            c_company = str(contact.get("company_name") or "").strip().lower()
            if exact:
                if c_name == target or c_company == target:
                    return contact
            else:
                if target in c_name or target in c_company:
                    return contact
    except Exception as exc:
        logger.warning(f"Error searching contacts by name '{name_cleaned}': {exc}")

    return None


def fetch_active_customers_map(
    books_client: Any,
    key_field: str = "contact_id",
    status: str = "active",
) -> Dict[str, Dict[str, Any]]:
    """Fetch all customers from Zoho Books and return an indexed dictionary.

    Keys are extracted from either direct attributes or custom fields using `key_field`.
    """
    params = {
        "contact_type": "customer",
        "status": status,
    }
    customer_map: Dict[str, Dict[str, Any]] = {}

    try:
        contacts = _get_contacts_iterable(books_client.contacts, params)
        for contact in contacts:
            key_val = contact.get(key_field)
            if key_val is None:
                key_val = get_custom_field_value(contact, key_field)

            if key_val is not None:
                clean_key = str(key_val).strip()
                if clean_key:
                    customer_map[clean_key] = contact
    except Exception as exc:
        logger.error(f"Error building customer map with key '{key_field}': {exc}")
        raise

    return customer_map
