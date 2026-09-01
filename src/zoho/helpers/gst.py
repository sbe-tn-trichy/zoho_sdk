"""GST (Goods and Services Tax) identification and validation helpers."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$"
)


def normalize_gstin(value: Any) -> str:
    """Normalize a GSTIN by removing non-alphanumeric characters and converting to uppercase."""
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def is_valid_gstin(value: Any) -> bool:
    """Check whether a value is a valid 15-character Indian GSTIN."""
    cleaned = normalize_gstin(value)
    return bool(GSTIN_PATTERN.match(cleaned))


def group_contacts_by_gstin(
    contacts: Iterable[Mapping[str, Any]],
) -> Dict[str, List[Mapping[str, Any]]]:
    """Group contact records by their normalized valid GSTIN."""
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for contact in contacts:
        raw_gst = contact.get("gst_no") or contact.get("gstin")
        if not raw_gst:
            # Check custom fields
            custom_fields = contact.get("custom_fields")
            if isinstance(custom_fields, list):
                for cf in custom_fields:
                    if isinstance(cf, dict) and str(cf.get("api_name") or "").lower() in ("gstin", "gst_no"):
                        raw_gst = cf.get("value")
                        break
        normalized = normalize_gstin(raw_gst)
        if is_valid_gstin(normalized):
            grouped[normalized].append(contact)
    return dict(grouped)
