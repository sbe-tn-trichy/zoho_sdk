"""Generic document-number parsing shared by resources and workflows."""

import re


def parse_doc_number(doc_no: str) -> tuple[str, int, int]:
    """Return prefix, trailing integer and observed width; width zero means no suffix."""
    value = str(doc_no or "").strip()
    match = re.fullmatch(r"(.*?)(\d+)", value)
    if not match:
        return value, 0, 0
    prefix, suffix = match.groups()
    return prefix, int(suffix), len(suffix)


__all__ = ["parse_doc_number"]
