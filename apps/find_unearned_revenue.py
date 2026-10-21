#!/usr/bin/env python3
"""Find current unused customer payments for Unearned Revenue review (read-only)."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_analytics_client
from workflows.analytics_catalog import AnalyticsCatalog
from workflows.core.checkpoint import write_atomic_json
from workflows.unearned_revenue import DEFAULT_UNEARNED_ACCOUNT_ID, review_unearned_revenue_analytics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", default=DEFAULT_UNEARNED_ACCOUNT_ID)
    parser.add_argument("--output", type=Path, default=Path("output/unearned_revenue.json"))
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--catalog-dir", type=Path, default=None)
    args = parser.parse_args()
    catalog = AnalyticsCatalog(None, args.workspace_id, args.catalog_dir or Path("workspace_metadata") / args.workspace_id)
    metadata = catalog.analyze()
    review = review_unearned_revenue_analytics(get_analytics_client(),
        workspace_id=args.workspace_id, account_id=args.account_id)
    write_atomic_json(args.output, {"checked_at": datetime.now(timezone.utc).isoformat(),
        "last_successful_metadata_sync_at": metadata["last_successful_sync_at"], **review})
    print(f"Last successful metadata sync (UTC): {metadata['last_successful_sync_at']}")
    print(f"Unused payments: {len(review['payments'])}; customers: {len(review['customers'])}")
    print(f"Unused payment total (BCY): {review['unused_payment_total_bcy']}")
    print(f"Account net credit (BCY): {review['account_net_credit_bcy']}")
    print(f"Ledger less unused payments (BCY): {review['ledger_less_unused_bcy']}")
    print(f"Report: {args.output}")
    for limitation in review["limitations"]:
        print(limitation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
