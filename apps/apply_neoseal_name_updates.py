#!/usr/bin/env python3
"""Apply approved naming conventions, SKU corrections, and SI standards to Zoho Books items.

Default behavior is DRY-RUN. To mutate Books items, pass --apply explicitly.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.neoseal_audit import (
    KNOWN_DUPLICATE_MAP,
    compute_item_update,
    standardize_item_name,
)

logger = logging.getLogger("apply_neoseal_name_updates")
DEFAULT_PURCHASE_ACCOUNT_ID = "1094368000034919918"


def load_items_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load items from an exported inventory CSV."""
    with csv_path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purchase-account-id",
        default=DEFAULT_PURCHASE_ACCOUNT_ID,
        help=f"Zoho Books purchase account ID for Neoseal (default: {DEFAULT_PURCHASE_ACCOUNT_ID})",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="Optional local CSV snapshot to evaluate instead of querying Books API",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute mutations against Zoho Books API (default: dry-run mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Force dry-run inspection without mutating Zoho Books (enabled by default)",
    )
    parser.add_argument(
        "--item-id",
        type=str,
        help="Target only a single specific item ID for evaluation or update",
    )
    parser.add_argument(
        "--deactivate-duplicates",
        action="store_true",
        default=False,
        help="Deactivate zero-stock duplicate items in Books (e.g. 701-260-B, 701-260-W)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory where pre-update snapshots and audit reports are written",
    )
    return parser


def run_plan_or_apply(
    items: Sequence[Mapping[str, Any]],
    apply: bool = False,
    deactivate_duplicates: bool = False,
    target_item_id: Optional[str] = None,
    client: Optional[Any] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluate items, generate planned updates, and optionally mutate Zoho Books."""
    output_dir = output_dir or Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # 1. Save pre-update backup snapshot
    snapshot_path = output_dir / f"neoseal_pre_update_snapshot_{ts}.json"
    with snapshot_path.open("w", encoding="utf-8") as f:
        json.dump([dict(it) for it in items], f, indent=2)

    # 2. Compute updates
    planned_updates: List[Dict[str, Any]] = []
    for it in items:
        item_id = str(it.get("item_id") or "").strip()
        if target_item_id and item_id != target_item_id:
            continue
        update = compute_item_update(it)
        if update:
            planned_updates.append(update)

    audit_records: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0

    if not apply:
        # DRY-RUN
        for p in planned_updates:
            audit_records.append({
                "item_id": p["item_id"],
                "status": "dry_run",
                "current_name": p["current_name"],
                "proposed_name": p["proposed_name"],
                "current_sku": p["current_sku"],
                "proposed_sku": p["proposed_sku"],
                "is_duplicate": p["is_duplicate"],
                "reasons": p["reasons"],
            })
    else:
        # LIVE MUTATION
        if not client:
            raise ValueError("Live client required when apply=True")

        for p in planned_updates:
            record: Dict[str, Any] = {
                "item_id": p["item_id"],
                "current_name": p["current_name"],
                "proposed_name": p["proposed_name"],
                "current_sku": p["current_sku"],
                "proposed_sku": p["proposed_sku"],
                "reasons": p["reasons"],
            }
            try:
                payload: Dict[str, Any] = {}
                if p["name_changed"]:
                    payload["name"] = p["proposed_name"]
                if p["sku_changed"]:
                    payload["sku"] = p["proposed_sku"]

                if payload:
                    client.items.update(p["item_id"], payload)
                    record["update_status"] = "success"
                    record["payload"] = payload
                else:
                    record["update_status"] = "skipped_no_field_change"

                if deactivate_duplicates and p["is_duplicate"]:
                    client.items.mark_as_inactive(p["item_id"])
                    record["deactivated"] = True

                success_count += 1
                record["status"] = "success"
            except Exception as exc:
                failure_count += 1
                record["status"] = "failed"
                record["error"] = str(exc)
                logger.error("Failed to update item %s: %s", p["item_id"], exc)

            audit_records.append(record)

    summary = {
        "timestamp": ts,
        "mode": "live_apply" if apply else "dry_run",
        "total_items_evaluated": len(items),
        "updates_required": len(planned_updates),
        "success_count": success_count if apply else 0,
        "failure_count": failure_count if apply else 0,
        "backup_snapshot": str(snapshot_path),
        "records": audit_records,
    }

    # Save audit log
    audit_path = output_dir / "neoseal_name_updates_audit.json"
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve dry-run vs apply
    is_apply = args.apply and not args.dry_run

    client = None
    if args.input_csv:
        print(f"Loading items from local CSV: {args.input_csv}")
        items = load_items_from_csv(args.input_csv)
    else:
        print(f"Querying Zoho Books API for purchase account {args.purchase_account_id}...")
        client = get_books_client()
        items = client.items.list_by_purchase_account(args.purchase_account_id)

    if not items:
        print("No items found to evaluate.")
        return 0

    if is_apply and client is None:
        client = get_books_client()

    print(f"\nEvaluating {len(items)} items...")
    summary = run_plan_or_apply(
        items=items,
        apply=is_apply,
        deactivate_duplicates=args.deactivate_duplicates,
        target_item_id=args.item_id,
        client=client,
        output_dir=args.output_dir,
    )

    records = summary["records"]
    print(f"\nFound {len(records)} items requiring updates:")
    print("=" * 100)
    print(f"{'Item ID':<20} | {'Current Name -> Proposed Name':<50} | {'SKU Update':<20}")
    print("-" * 100)
    for r in records:
        name_str = f"{r['current_name']} -> {r['proposed_name']}" if r.get("current_name") != r.get("proposed_name") else r.get("current_name", "")
        sku_str = f"{r['current_sku']} -> {r['proposed_sku']}" if r.get("current_sku") != r.get("proposed_sku") else "-"
        print(f"{r['item_id']:<20} | {name_str[:50]:<50} | {sku_str:<20}")
    print("=" * 100)

    print(f"\nPre-update backup snapshot: {summary['backup_snapshot']}")
    print(f"Audit report written to: {args.output_dir / 'neoseal_name_updates_audit.json'}")

    if not is_apply:
        print("\n" + "#" * 70)
        print(" [DRY-RUN COMPLETE] No mutations were made to Zoho Books.")
        print(" To execute these changes live against Zoho Books, rerun with:")
        print("   python apps/apply_neoseal_name_updates.py --apply")
        print("#" * 70 + "\n")
    else:
        print("\n" + "#" * 70)
        print(f" [LIVE APPLY COMPLETE] Successfully updated {summary['success_count']} items.")
        if summary["failure_count"] > 0:
            print(f" WARNING: {summary['failure_count']} updates failed. Check audit report for details.")
        print("#" * 70 + "\n")

    return 0 if summary["failure_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
