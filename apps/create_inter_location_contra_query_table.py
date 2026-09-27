"""Create a live Zoho Analytics Query Table for clearing-account location differences."""

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
    parser.add_argument("--name", default="Inter Location Contra FY25-27")
    parser.add_argument("--apply", action="store_true", help="Save the Query Table in Zoho Analytics")
    args = parser.parse_args(argv)

    analytics = get_analytics_client(org_id=Config.ANALYTICS_ORG_ID)
    result = sync_inter_location_contra_query_table(
        analytics,
        workspace_id=args.workspace_id,
        account_id=args.account_id,
        name=args.name,
        apply=args.apply,
    )
    print(
        f"Validated {result['validated_pair_count']} inter-location pairs across {result['preview_row_count']} allocation rows."
    )
    if not args.apply:
        print("Dry run: no Query Table created. Use --apply to save it.")
        return 0

    print(f"Created and verified Query Table {result['view_id']} ({result.get('saved_row_count', 0)} pairs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
