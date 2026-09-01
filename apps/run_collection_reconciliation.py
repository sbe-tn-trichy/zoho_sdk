#!/usr/bin/env python3
"""Run the Collection Reconciliation workflow in a single step.

This script initializes Zoho Creator, Books, and Analytics clients (via HttpTokenProvider or explicit tokens),
configures the CollectionReconciler, and executes the end-to-end reconciliation flow.

Outputs are written under `output/collection_reconciliation/`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from workflows.collection_reconciliation import (
    CollectionReconciler,
    CollectionReconciliationConfig,
)
from workflows.core.auth import (
    get_analytics_client,
    get_books_client,
    get_creator_client,
)
from workflows.core.config import Config
from zoho import ZohoAnalyticsAPI, ZohoBooksAPI, ZohoCreatorAPI

logger = logging.getLogger("run_collection_reconciliation")


def run_collection_reconciliation(
    bank_account_id: Optional[str] = None,
    creator_app_link_name: Optional[str] = None,
    creator_owner_name: Optional[str] = None,
    analytics_workspace_id: Optional[str] = None,
    dry_run: bool = True,
    token_url: str = Config.TOKEN_URL,
    org_id: str = Config.ORG_ID,
    domain: str = Config.DOMAIN,
    output_path: Optional[Path] = None,
    creator_client: Optional[ZohoCreatorAPI] = None,
    books_client: Optional[ZohoBooksAPI] = None,
    analytics_client: Optional[ZohoAnalyticsAPI] = None,
) -> Dict[str, Any]:
    """Execute collection reconciliation in a single function call.

    Args:
        bank_account_id: Target Books bank account ID (defaults to BANK_ACCOUNT_HDFC or env/Config)
        creator_app_link_name: Creator app link name (defaults to PAYMENT_CREATOR_APP_LINK_NAME or 'order-management-new')
        creator_owner_name: Creator account owner name (defaults to CREATOR_ACCOUNT_OWNER_NAME or 'bharathdst')
        analytics_workspace_id: Optional Analytics workspace ID for exception matching
        dry_run: If True (default), simulates updates without writing to Books/Creator.
        token_url: URL for HTTP token broker.
        org_id: Zoho Books Organization ID.
        domain: Zoho domain region ('com', 'in', etc.).
        output_path: Path to write output summary JSON (defaults to output/collection_reconciliation/...)
        creator_client: Pre-instantiated ZohoCreatorAPI client (optional).
        books_client: Pre-instantiated ZohoBooksAPI client (optional).
        analytics_client: Pre-instantiated ZohoAnalyticsAPI client (optional).

    Returns:
        Dict summarizing confirmed, unmatched, and failed records along with stats.
    """
    bank_id = bank_account_id or Config.BANK_ACCOUNT_HDFC
    if not bank_id:
        raise ValueError(
            "Bank account ID is required. Pass bank_account_id or configure BANK_ACCOUNT_HDFC."
        )

    creator_app = creator_app_link_name or os.environ.get(
        "PAYMENT_CREATOR_APP_LINK_NAME", "order-management-new"
    )
    creator_owner = creator_owner_name or os.environ.get(
        "CREATOR_ACCOUNT_OWNER_NAME", "bharathdst"
    )

    if not creator_client:
        creator_client = get_creator_client(
            owner_name=creator_owner,
            domain=domain,
            token_url=token_url,
        )

    if not books_client:
        books_client = get_books_client(
            org_id=org_id,
            domain=domain,
            token_url=token_url,
        )

    if not analytics_client and analytics_workspace_id:
        analytics_client = get_analytics_client(
            org_id=org_id,
            domain=domain,
            token_url=token_url,
        )

    config = CollectionReconciliationConfig(
        creator_app_link_name=creator_app,
        bank_account_id=bank_id,
        analytics_workspace_id=analytics_workspace_id,
        dry_run=dry_run,
    )

    reconciler = CollectionReconciler(
        creator_client=creator_client,
        books_client=books_client,
        analytics_client=analytics_client,
        config=config,
    )

    logger.info("Starting collection reconciliation (dry_run=%s)", dry_run)
    result = reconciler.reconcile_pending()

    confirmed_count = len(result.get("confirmed", []))
    unmatched_count = len(result.get("unmatched", []))
    failed_count = len(result.get("failed", []))

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "bank_account_id": bank_id,
        "creator_app": creator_app,
        "config": {
            "bank_account_id": bank_id,
            "creator_app_link_name": creator_app,
        },
        "counts": {
            "confirmed": confirmed_count,
            "unmatched": unmatched_count,
            "failed": failed_count,
            "total": confirmed_count + unmatched_count + failed_count,
        },
        "confirmed": result.get("confirmed", []),
        "unmatched": result.get("unmatched", []),
        "failed": result.get("failed", []),
    }

    if output_path is None:
        mode_str = "dry_run" if dry_run else "live"
        output_dir = Path("output/collection_reconciliation")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"reconciliation_summary_{mode_str}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info("Reconciliation complete. Summary saved to %s", output_path)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bank-account-id",
        help="Books bank account ID (default: BANK_ACCOUNT_HDFC config)",
    )
    parser.add_argument(
        "--creator-app",
        default="order-management-new",
        help="Creator app link name",
    )
    parser.add_argument(
        "--creator-owner",
        default="bharathdst",
        help="Creator account owner name",
    )
    parser.add_argument(
        "--analytics-workspace-id",
        help="Zoho Analytics workspace ID for customer exceptions",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute live mutations (default is dry-run mode)",
    )
    parser.add_argument(
        "--token-url",
        default=Config.TOKEN_URL,
        help="URL for HTTP token broker",
    )
    parser.add_argument(
        "--org-id",
        default=Config.ORG_ID,
        help="Zoho Books Organization ID",
    )
    parser.add_argument(
        "--domain",
        default=Config.DOMAIN,
        help="Zoho data-center domain region ('com', 'in', etc.)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Custom output path for JSON summary",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    dry_run = not args.execute
    if dry_run:
        logger.info("Running in DRY-RUN mode. Use --execute to apply mutations.")

    summary = run_collection_reconciliation(
        bank_account_id=args.bank_account_id,
        creator_app_link_name=args.creator_app,
        creator_owner_name=args.creator_owner,
        analytics_workspace_id=args.analytics_workspace_id,
        dry_run=dry_run,
        token_url=args.token_url,
        org_id=args.org_id,
        domain=args.domain,
        output_path=args.output,
    )

    print(json.dumps(summary["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
