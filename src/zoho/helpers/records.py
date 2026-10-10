"""Fetch resource details with explicit response-shape and identity checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class _RecordResource(Protocol):
    def get(self, identifier: str) -> Mapping[str, Any]: ...


def get_verified_record(
    resource: _RecordResource, identifier: str, key: str, id_key: str,
) -> dict[str, Any]:
    """Fetch a dictionary detail and verify its ID against the requested ID.

    ``key`` selects the response envelope and ``id_key`` selects the record ID.
    Numeric response IDs are compared as strings. Invalid response shapes,
    missing IDs and mismatched IDs raise ValueError; resource errors propagate.
    """
    response = resource.get(identifier)
    record = response.get(key) if isinstance(response, Mapping) else None
    if (not isinstance(record, dict) or record.get(id_key) is None
            or str(record[id_key]) != identifier):
        raise ValueError(f"Resource returned an invalid {key} detail for {identifier}")
    return record
