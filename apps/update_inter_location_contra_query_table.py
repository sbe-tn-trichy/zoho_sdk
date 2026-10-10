"""Compatibility command for inter-location Query Table update; prefer the manager."""

from __future__ import annotations

from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

try:
    from .manage_inter_location_contra_query_table import main as _manage
except ImportError:
    from manage_inter_location_contra_query_table import main as _manage


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Retain the historical command defaults using the shared manager."""
    return _manage(argv, default_view_id='264324000008274019')


if __name__ == "__main__":
    raise SystemExit(main())
