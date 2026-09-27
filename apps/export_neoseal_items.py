#!/usr/bin/env python3
"""Export Inventory items for a purchase account and flag missing vendor aliases."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_inventory_client
from workflows.neoseal_audit.exporter import (
    FIELDS,
    export_inventory_items,
    export_row,
    write_export_rows as _write_rows,
)


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
    rows, missing = export_inventory_items(
        get_inventory_client(),
        args.purchase_account_id,
        status="active",
        output_path=args.output,
        missing_output_path=args.missing_output,
    )
    print(f"Exported {len(rows)} items; {len(missing)} missing aliases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
