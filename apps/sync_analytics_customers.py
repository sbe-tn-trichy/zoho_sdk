#!/usr/bin/env python3
"""Sync three Analytics sources into four local customer tables, preserving cleanup edits."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.analytics_catalog import AnalyticsCatalog
from workflows.core.auth import get_analytics_client
from workflows.core.config import Config
from workflows.customer_analytics_sync import sync_analytics_customers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('output/customer_cleanup/normalized_customers.sqlite3'))
    parser.add_argument('--workspace-id', default='264324000000002043')
    parser.add_argument('--catalog-dir', type=Path, help='Cached metadata directory; never refreshed by this workflow')
    parser.add_argument('--source', type=Path, help='Replay a previously completed source export without network access')
    args = parser.parse_args()
    catalog_dir = args.catalog_dir or Path('workspace_metadata') / args.workspace_id
    result = sync_analytics_customers(
        get_analytics_client() if args.source is None else None,
        AnalyticsCatalog(None, args.workspace_id, catalog_dir), args.db,
        organization_id=str(Config.ORG_ID), source=args.source)
    print(json.dumps(asdict(result), default=str))


if __name__ == '__main__':
    main()
