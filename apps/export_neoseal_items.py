#!/usr/bin/env python3
"""Export Books items for a purchase account and flag missing vendor aliases."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client


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
    """Return the stable CSV representation of one Books item."""
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


def _write_rows(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purchase-account-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/neoseal_items.csv"),
    )
    parser.add_argument(
        "--missing-output",
        type=Path,
        default=Path("output/neoseal_items_missing_alias.csv"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    items = get_books_client().items.list_by_purchase_account(
        args.purchase_account_id,
        status="active",
    )
    rows = [export_row(item) for item in items]
    missing = [row for row in rows if row["has_alias_name"] == "false"]
    _write_rows(args.output, rows)
    _write_rows(args.missing_output, missing)
    print(f"Exported {len(rows)} items; {len(missing)} missing aliases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
