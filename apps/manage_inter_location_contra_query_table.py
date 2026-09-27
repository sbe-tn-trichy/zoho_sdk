#!/usr/bin/env python3
"""Manage (preview, create, or update) the inter-location contra Zoho Analytics Query Table."""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_analytics_client
from workflows.core.config import Config
from workflows.inter_location_analytics_report import sync_inter_location_contra_query_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", default="1094368000002033114")
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--view-id", default=None, help="If provided, updates this existing Query Table")
    parser.add_argument("--name", default="Inter Location Contra FY25-27")
    parser.add_argument("--apply", action="store_true", help="Save/Update the Query Table in Zoho Analytics")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    analytics = get_analytics_client(org_id=Config.ANALYTICS_ORG_ID)
    result = sync_inter_location_contra_query_table(
        analytics,
        workspace_id=args.workspace_id,
        account_id=args.account_id,
        view_id=args.view_id,
        name=args.name,
        apply=args.apply,
    )
    print(
        f"Validated {result['validated_pair_count']} location differences across {result['preview_row_count']} report rows."
    )
    if not args.apply:
        action = "update" if args.view_id else "create"
        print(f"Dry run: no Query Table {action}d. Use --apply to save changes.")
        return 0

    action = "Updated" if args.view_id else "Created"
    print(f"{action} and verified Query Table {result['view_id']} ({result.get('saved_row_count', 0)} rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
