"""Utilities for safely inspecting, extracting, and provisioning Zoho custom field values."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence


def _normalized_field_name(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def get_custom_field_value(
    record: Mapping[str, Any],
    field_name: str,
    default: Optional[Any] = None,
) -> Any:
    """Extract a custom field value from a Zoho record across various response shapes.

    Supports:
    1. Direct top-level key matching `field_name`.
    2. Items in `custom_fields` list matching `api_name`, `label`, or `customfield_id`.
    3. Keys in `custom_field_hash` dictionary.
    """
    if not record or not field_name:
        return default

    # 1. Direct top-level key
    if field_name in record:
        val = record.get(field_name)
        return val if val is not None else default

    # 2. Key inside custom_field_hash
    cf_hash = record.get("custom_field_hash")
    if isinstance(cf_hash, dict) and field_name in cf_hash:
        val = cf_hash.get(field_name)
        return val if val is not None else default

    # 3. List of custom field objects: [{'api_name': ..., 'label': ..., 'value': ...}]
    custom_fields = record.get("custom_fields")
    if isinstance(custom_fields, list):
        target = field_name.strip().lower()
        for cf in custom_fields:
            if not isinstance(cf, dict):
                continue
            api_name = str(cf.get("api_name") or "").strip().lower()
            label = str(cf.get("label") or "").strip().lower()
            cf_id = str(cf.get("customfield_id") or "").strip().lower()

            if target in (api_name, label, cf_id):
                val = cf.get("value")
                return val if val is not None else default

    return default


def extract_custom_fields_dict(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract all custom fields in a record into a flat dictionary keyed by api_name or label."""
    if not record:
        return {}

    result: Dict[str, Any] = {}

    cf_hash = record.get("custom_field_hash")
    if isinstance(cf_hash, dict):
        result.update(cf_hash)

    custom_fields = record.get("custom_fields")
    if isinstance(custom_fields, list):
        for cf in custom_fields:
            if not isinstance(cf, dict):
                continue
            key = cf.get("api_name") or cf.get("label") or cf.get("customfield_id")
            if key:
                result[str(key)] = cf.get("value")

    return result


def ensure_books_custom_fields(
    books_client: Any,
    entity: str,
    requirements: Sequence[Mapping[str, Any]],
    create_missing: bool = False,
) -> Dict[str, Any]:
    """Verify and optionally provision custom fields on a Zoho Books entity."""
    existing = books_client.custom_fields.list_for_entity(entity)
    existing_by_name: Dict[str, Dict[str, Any]] = {}
    for field in existing:
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or "")
        api_name = str(field.get("api_name") or "")
        if api_name.startswith("cf_"):
            api_name = api_name[3:]
        for name in (label, api_name):
            normalized = _normalized_field_name(name)
            if normalized:
                existing_by_name[normalized] = field

    missing: List[Dict[str, Any]] = []
    misconfigured: List[Dict[str, Any]] = []
    for requirement in requirements:
        normalized = _normalized_field_name(requirement.get("label"))
        field = existing_by_name.get(normalized)
        if field is None:
            missing.append(dict(requirement))
            continue
        problems: List[str] = []
        if requirement.get("data_type") and str(field.get("data_type") or "") != requirement["data_type"]:
            problems.append(f"data_type must be {requirement['data_type']!r}")
        if requirement.get("is_unique") and field.get("is_unique") is not True:
            problems.append("field must be unique")
        required_values = {
            str(row["name"])
            for row in requirement.get("values", [])
            if isinstance(row, dict) and row.get("name")
        }
        actual_values = {
            str(row.get("name") or row.get("value") or "")
            for row in field.get("values", [])
            if isinstance(row, dict)
        }
        absent_values = sorted(required_values - actual_values)
        if absent_values:
            problems.append("missing dropdown values: " + ", ".join(absent_values))
        if problems:
            misconfigured.append({"field": requirement.get("label", ""), "problems": problems})

    created: List[Dict[str, Any]] = []
    if create_missing:
        for requirement in missing:
            created.append(books_client.custom_fields.create(requirement))
        missing = []

    return {
        "valid": not missing and not misconfigured,
        "missing": missing,
        "misconfigured": misconfigured,
        "created": created,
    }
