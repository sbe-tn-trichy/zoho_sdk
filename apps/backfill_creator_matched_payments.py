#!/usr/bin/env python3
"""Backfill Creator identifiers onto existing Books customer payments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.creator_books_payment_link import (
    BackfillConfig,
    BackfillResult,
    CreatorBooksPaymentLinkBackfill,
    build_native_payment_indexes,
    classify_links,
    find_creator_sequence_gaps,
    resolve_books_payment,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-batch", action="store_true")
    parser.add_argument("--creator-record-id")
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--creator-report", default="matched")
    parser.add_argument("--creator-crosscheck-report", default="All_Payments")
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--checkpoint-path", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = BackfillConfig(
        location_id=args.location_id,
        execute=args.execute,
        allow_batch=args.allow_batch,
        creator_record_id=args.creator_record_id,
        creator_app=args.creator_app,
        creator_report=args.creator_report,
        creator_crosscheck_report=args.creator_crosscheck_report,
        resume_from=args.resume_from,
        **({"checkpoint_path": args.checkpoint_path} if args.checkpoint_path else {}),
    )
    result = CreatorBooksPaymentLinkBackfill(
        get_creator_client(), get_books_client(), config
    ).run()
    print(json.dumps(result.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
