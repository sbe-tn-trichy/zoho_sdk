"""Lossless, labeled references shared by transaction narrations."""
from __future__ import annotations

import re
from collections.abc import Sequence

_LINE = re.compile(r'^([A-Z][A-Z0-9_]*(?:#)?):[ \t]*(.*)$')


def format_reference_lines(values: Sequence[tuple[str, str]]) -> str:
    """Format ordered pairs; repeated labels represent multiple source documents."""
    lines = []
    for label, value in values:
        if not _LINE.fullmatch(label + ': ') or any(c in value for c in '\r\n'):
            raise ValueError('References require uppercase labels and single-line values')
        if not value.strip():
            raise ValueError('Reference values must be nonempty')
        lines.append(f'{label}: {value.strip()}')
    return '\n'.join(lines)


def parse_reference_lines(text: str) -> dict[str, list[str]]:
    """Keep duplicate keys rather than overwriting combined-document references."""
    result: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _LINE.fullmatch(line.strip())
        if match:
            result.setdefault(match[1], []).append(match[2].strip())
    return result


def update_reference_lines(text: str, values: Sequence[tuple[str, str]], *,
                           managed_labels: Sequence[str]) -> str:
    """Replace managed lines idempotently, preserving unrelated human notes."""
    block = format_reference_lines(values)
    retained = []
    for line in text.splitlines():
        match = _LINE.fullmatch(line.strip())
        if not match or match[1] not in managed_labels:
            retained.append(line)
    return '\n'.join(x for x in ('\n'.join(retained).strip(), block) if x)
