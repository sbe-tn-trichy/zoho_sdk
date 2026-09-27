"""Add invoice and bill location details to the existing inter-location Query Table."""

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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", default="1094368000002033114")
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--view-id", default="264324000008274019")
    parser.add_argument("--apply", action="store_true", help="Update the saved Query Table")
    args = parser.parse_args(argv)

    analytics = get_analytics_client(org_id=Config.ANALYTICS_ORG_ID)
    result = sync_inter_location_contra_query_table(
        analytics,
        workspace_id=args.workspace_id,
        account_id=args.account_id,
        view_id=args.view_id,
        apply=args.apply,
    )
    print(
        f"Validated {result['validated_pair_count']} location differences across {result['preview_row_count']} report rows."
    )
    if not args.apply:
        print("Dry run: saved Query Table not changed. Use --apply to update it.")
        return 0

    print(f"Updated and verified Query Table {args.view_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
