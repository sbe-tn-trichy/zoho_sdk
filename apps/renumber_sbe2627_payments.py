"""Script to renumber SBE2627CP- customer payments dated in FY 2025-26 to the SBE2526CP- sequence in Zoho Books."""

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_ROOT = Path("d:/workplace/zoho_sdk").resolve()
sys.path.insert(0, str(WORKSPACE_ROOT / "zoho_sdk" / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from workflows.core.auth import get_analytics_client, get_books_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def get_target_payments() -> Tuple[List[Dict[str, Any]], int]:
    """Fetch payments from Zoho Analytics and identify target payments + max existing 2526 sequence."""
    analytics = get_analytics_client()
    workspace_id = "264324000000002043"

    query = """
    SELECT 
        "Payment ID",
        "Payment Number",
        "Payment Date",
        "Customer ID",
        "Payment Mode",
        "Amount (BCY)",
        "Location ID",
        "Reference Number"
    FROM "Customer Payments (Zoho Books)"
    """
    records = analytics.queries.execute(workspace_id=workspace_id, sql_query=query, max_attempts=30)

    # Find highest existing SBE2526CP number (excluding any previously renumbered ones from our batch)
    max_2526_num = 0
    for r in records:
        p_num = str(r.get("Payment Number") or "").strip()
        if p_num.startswith("SBE2526CP-"):
            m = re.match(r"^SBE2526CP-(\d+)$", p_num)
            if m:
                # Original max was 3334
                val = int(m.group(1))
                if val <= 3334:
                    max_2526_num = max(max_2526_num, val)

    if max_2526_num == 0:
        max_2526_num = 3334

    # Target: SBE2627CP- dated 01/04/2025 to 31/03/2026 (or already renumbered first payment)
    start_dt = datetime(2025, 4, 1)
    end_dt = datetime(2026, 3, 31, 23, 59, 59)

    targets = []
    for r in records:
        p_num = str(r.get("Payment Number") or "").strip()
        p_id = str(r.get("Payment ID"))
        dt = parse_date(r.get("Payment Date"))
        
        # Include SBE2627CP- in FY 25-26, or the one we just updated (SBE2526CP-03335 with ID 1094368000044905213)
        if (p_num.startswith("SBE2627CP-") or p_id == "1094368000044905213") and dt and start_dt <= dt <= end_dt:
            targets.append({
                "payment_id": p_id,
                "current_payment_number": p_num if p_num.startswith("SBE2627CP-") else "SBE2627CP-01795",
                "payment_date": dt.strftime("%Y-%m-%d"),
                "payment_date_display": dt.strftime("%d/%m/%Y"),
                "dt": dt,
                "amount": r.get("Amount (BCY)"),
                "payment_mode": r.get("Payment Mode"),
                "customer_id": r.get("Customer ID"),
            })

    # Sort chronologically by date, then by original payment number
    targets.sort(key=lambda x: (x["dt"], x["current_payment_number"]))
    return targets, max_2526_num


def build_renumber_plan(targets: List[Dict[str, Any]], starting_sequence: int) -> List[Dict[str, Any]]:
    """Build the renumbering mapping assigning sequential SBE2526CP- numbers."""
    plan = []
    seq = starting_sequence
    for t in targets:
        suffix_str = f"{seq:05d}"
        new_num = f"SBE2526CP-{suffix_str}"
        plan.append({
            "payment_id": t["payment_id"],
            "current_payment_number": t["current_payment_number"],
            "new_payment_number": new_num,
            "prefix": "SBE2526CP-",
            "suffix": suffix_str,
            "payment_date": t["payment_date_display"],
            "date_iso": t["payment_date"],
            "amount": str(t["amount"]).encode("ascii", "replace").decode("ascii"),
            "payment_mode": t["payment_mode"],
            "customer_id": t["customer_id"],
        })
        seq += 1
    return plan


def update_payment_in_books(books_client: Any, payment_id: str, prefix: str, suffix: str) -> Dict[str, Any]:
    """Update payment prefix and suffix in Zoho Books."""
    payload = {
        "payment_number_prefix": prefix,
        "payment_number_suffix": suffix,
    }
    return books_client.customer_payments.update(payment_id, payload)


def execute_renumbering(plan: List[Dict[str, Any]], execute: bool = False) -> List[Dict[str, Any]]:
    """Execute or simulate the renumbering plan."""
    results = []
    books_client = get_books_client() if execute else None

    print(f"\n{'#' * 115}")
    print(f" {'EXECUTION PHASE' if execute else 'DRY-RUN SIMULATION'}: Renumbering {len(plan)} Customer Payments")
    print(f"{'#' * 115}\n")

    for idx, item in enumerate(plan, 1):
        pmt_id = item["payment_id"]
        old_num = item["current_payment_number"]
        new_num = item["new_payment_number"]
        prefix = item["prefix"]
        suffix = item["suffix"]
        dt = item["payment_date"]
        amt = item["amount"]

        if not execute:
            print(f"[{idx:02d}/{len(plan)}] DRY-RUN: {old_num} -> {new_num} | Date: {dt} | Amount: {amt}")
            results.append({
                **item,
                "status": "planned",
                "updated_at": None,
                "error": None,
            })
        else:
            print(f"[{idx:02d}/{len(plan)}] EXECUTING: {old_num} -> {new_num} (ID: {pmt_id})...", end=" ", flush=True)
            try:
                res = update_payment_in_books(books_client, pmt_id, prefix=prefix, suffix=suffix)
                print("SUCCESS")
                results.append({
                    **item,
                    "status": "success",
                    "updated_at": datetime.now().isoformat(),
                    "error": None,
                })
                # Polite rate-limiting
                time.sleep(0.3)
            except Exception as exc:
                print(f"FAILED: {exc}")
                results.append({
                    **item,
                    "status": "failed",
                    "updated_at": datetime.now().isoformat(),
                    "error": str(exc),
                })

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Renumber SBE2627CP- customer payments in FY 2025-26 to SBE2526CP- sequence."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually apply mutations to Zoho Books. Defaults to Dry Run.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE_ROOT / "output"),
        help="Directory to save audit plan",
    )
    args = parser.parse_args()

    print("Fetching payment records and checking sequence numbers in Zoho Analytics...")
    targets, max_existing_seq = get_target_payments()

    start_seq = max_existing_seq + 1
    print(f"Found {len(targets)} payments in FY 2025-26.")
    print(f"Base SBE2526CP- max number is SBE2526CP-{max_existing_seq:05d}.")
    print(f"Assigning new numbers sequentially from SBE2526CP-{start_seq:05d} to SBE2526CP-{start_seq + len(targets) - 1:05d}.\n")

    plan = build_renumber_plan(targets, starting_sequence=start_seq)
    results = execute_renumbering(plan, execute=args.execute)

    # Save audit file
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_file = out_dir / f"renumber_sbe2627_payments_{'executed' if args.execute else 'plan'}.json"
    audit_file.write_text(json.dumps({
        "mode": "execute" if args.execute else "dry-run",
        "generated_at": datetime.now().isoformat(),
        "total_payments": len(results),
        "starting_sequence": start_seq,
        "ending_sequence": start_seq + len(targets) - 1,
        "items": results,
    }, indent=2), encoding="utf-8")

    print(f"\n[OK] Plan/Audit report saved to: {audit_file}")


if __name__ == "__main__":
    main()
