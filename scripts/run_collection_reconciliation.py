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

from workflows.collection_reconciliation import (
    CollectionReconciler,
    CollectionReconciliationConfig,
)
from workflows.core.config import Config
from zoho import HttpTokenProvider, ZohoAnalyticsAPI, ZohoBooksAPI, ZohoCreatorAPI

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
        Dict[str, Any] containing execution summary and outputs.
    """
    bank_acc_id = bank_account_id or os.getenv("BANK_ACCOUNT_ID") or Config.BANK_ACCOUNT_HDFC
    app_link = creator_app_link_name or os.getenv("PAYMENT_CREATOR_APP_LINK_NAME", "order-management-new")
    owner_name = creator_owner_name or os.getenv("CREATOR_ACCOUNT_OWNER_NAME", "bharathdst")

    # Acquire tokens if clients were not explicitly supplied
    if not (creator_client and books_client):
        tokens = HttpTokenProvider(token_url, timeout=30).get_tokens()
        if not creator_client:
            creator_token = tokens.get("creator") or tokens.get("zoho_creator_conn") or ""
            creator_client = ZohoCreatorAPI(
                access_token=creator_token,
                account_owner_name=owner_name,
                domain=domain,
                send_environment_header=False,
            )
        if not books_client:
            books_token = tokens.get("books") or tokens.get("zoho_books_conn") or ""
            books_client = ZohoBooksAPI(
                access_token=books_token,
                organization_id=org_id,
                domain=domain,
            )

    if not analytics_client and analytics_workspace_id:
        try:
            tokens = HttpTokenProvider(token_url, timeout=30).get_tokens()
            analytics_token = tokens.get("analytics") or tokens.get("zoho_analytics_conn") or ""
            analytics_client = ZohoAnalyticsAPI(
                access_token=analytics_token,
                organization_id=org_id,
                domain=domain,
            )
        except Exception:
            logger.warning("Could not initialize Analytics client for workspace %s", analytics_workspace_id)

    reconcile_config = CollectionReconciliationConfig(
        creator_app_link_name=app_link,
        bank_account_id=bank_acc_id,
        analytics_workspace_id=analytics_workspace_id,
        dry_run=dry_run,
    )

    reconciler = CollectionReconciler(
        config=reconcile_config,
        creator_client=creator_client,
        books_client=books_client,
        analytics_client=analytics_client,
    )

    logger.info(
        "Starting Collection Reconciliation (dry_run=%s, app=%s, bank_account=%s)",
        dry_run,
        app_link,
        bank_acc_id,
    )
    result = reconciler.run()

    # Save output under output/ folder
    if output_path is None:
        output_path = Path("output/collection_reconciliation/collection_reconciliation_summary.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "config": {
            "creator_app_link_name": app_link,
            "bank_account_id": bank_acc_id,
            "analytics_workspace_id": analytics_workspace_id,
        },
        "result": result,
    }

    output_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    logger.info("Reconciliation summary written to %s", output_path)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Execute actual updates (disables dry_run)")
    parser.add_argument("--bank-account-id", help="Books bank account ID to reconcile")
    parser.add_argument("--creator-app", help="Creator application link name")
    parser.add_argument("--creator-owner", help="Creator account owner name")
    parser.add_argument("--analytics-workspace-id", help="Zoho Analytics workspace ID for SQL query exceptions")
    parser.add_argument("--token-url", default=Config.TOKEN_URL, help="Token broker URL")
    parser.add_argument("--org-id", default=Config.ORG_ID, help="Zoho Books Organization ID")
    parser.add_argument("--domain", default=Config.DOMAIN, help="Zoho Domain (e.g. in, com)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/collection_reconciliation/collection_reconciliation_summary.json"),
        help="Path for saving summary output JSON",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    summary = run_collection_reconciliation(
        bank_account_id=args.bank_account_id,
        creator_app_link_name=args.creator_app,
        creator_owner_name=args.creator_owner,
        analytics_workspace_id=args.analytics_workspace_id,
        dry_run=not args.execute,
        token_url=args.token_url,
        org_id=args.org_id,
        domain=args.domain,
        output_path=args.output,
    )

    print(json.dumps(summary["result"], indent=2, default=str))
    print(f"Summary saved to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
