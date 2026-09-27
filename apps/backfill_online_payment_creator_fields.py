#!/usr/bin/env python3
"""Backfill Creator payment checkpoints from existing Books customer payments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.online_payment_creator_backfill import (
    _creator_values,
    _normalized,
    _require_creator_update_success,
    _summary,
    _verify_creator_fields,
    _write_result,
    find_books_payment,
    run_backfill,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-batch", action="store_true")
    parser.add_argument("--creator-record-id")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/collection_reconciliation/online_payment_books_backfill.json"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_backfill(
        get_creator_client(),
        get_books_client(),
        creator_app=args.creator_app,
        execute=args.execute,
        allow_batch=args.allow_batch,
        creator_record_id=args.creator_record_id,
        checkpoint_path=args.output,
        resume_from=args.resume_from,
    )
    _write_result(args.output, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
