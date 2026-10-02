#!/usr/bin/env python3
"""Compare an AIS IT workbook with Zoho Books without changing transactions."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

try:
    from . import _bootstrap
except ImportError:
    import _bootstrap

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.ais_reconciliation import (
    CollectionConfig, collect_books_snapshot, read_ais_master, read_snapshot,
    reconcile_ais, write_report, write_snapshot,
)
from workflows.ais_reconciliation.sources import master_range


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("--org-id", default=Config.ORG_ID)
    parser.add_argument("--domain", default=Config.DOMAIN)
    parser.add_argument("--gstin", help="Recipient GSTIN (default: unique GSTIN in AIS purchases)")
    parser.add_argument("--sales-account-id", default="1094368000000000486")
    parser.add_argument("--exclude-location-id", default="1094368000044509446")
    parser.add_argument("--snapshot", type=Path, help="Replay a complete saved snapshot; no network reads")
    parser.add_argument("--max-requests", type=int, default=250)
    parser.add_argument("--request-interval", type=float, default=2.1)
    parser.add_argument("--output", type=Path, default=Path("output/ais_reconciliation"))
    args = parser.parse_args(argv)
    try:
        master = read_ais_master(args.master)
        gstins = {r["cells"]["E"] for name, rows in master.items()
                  if name.endswith(" GST purchases") for r in rows[1:] if r["cells"]["H"] == "Active"}
        if len(gstins) != 1 or (args.gstin and args.gstin not in gstins):
            raise ValueError("This workflow requires one recipient GSTIN matching the AIS master")
        gstin = args.gstin or next(iter(gstins))
        start, end = master_range(master)
        if args.snapshot:
            snapshot = read_snapshot(args.snapshot, organization_id=str(args.org_id), from_date=start, to_date=end)
        else:
            books = get_books_client(org_id=args.org_id, domain=args.domain)
            print("Collecting scoped Books lists, tax ledgers, bank windows and sales reports...", flush=True)
            snapshot = collect_books_snapshot(books, master, CollectionConfig(
                str(args.org_id), gstin, args.sales_account_id, args.exclude_location_id,
                args.request_interval, args.max_requests))
            write_snapshot(snapshot, args.output / "books_snapshot.json")
        report = reconcile_ais(master, snapshot, gstin=gstin, master_name=args.master.name)
        path = write_report(report, args.output)
    except Exception as exc:
        print(f"AIS comparison failed; no complete report generated: {exc}", file=sys.stderr)
        return 1
    stats = report["statistics"]
    print(f"Generated {path}\nGaps: {stats['missing']}; differences: {stats['differences']}; "
          f"unresolved mappings: {stats['unresolved']}\nSnapshot: {snapshot['metadata']['captured_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
