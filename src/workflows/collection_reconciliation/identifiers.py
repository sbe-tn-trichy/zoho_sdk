"""Extract identifiers from nested Creator and Books response records."""

from typing import Any, Mapping, Optional, Sequence


def identifier(payload: Any, keys: Sequence[str]) -> Optional[str]:
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                return str(value)
        for value in payload.values():
            found = identifier(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = identifier(value, keys)
            if found:
                return found
    return None


def identifiers(payload: Any, keys: Sequence[str]) -> set[str]:
    """Return every scalar identifier stored under any of ``keys``."""
    found: set[str] = set()
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                found.add(str(value))
        for value in payload.values():
            found.update(identifiers(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            found.update(identifiers(value, keys))
    return found
