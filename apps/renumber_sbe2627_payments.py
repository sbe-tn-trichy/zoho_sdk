"""Review or resume FY 2025-26 customer-payment renumbering; dry-run by default."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from . import _bootstrap
except ImportError:
    import _bootstrap

from workflows.core.auth import get_analytics_client, get_books_client
from workflows.core.checkpoint import write_atomic_json
from workflows.core.dates import get_fy_date_range
from workflows.payment_renumbering import build_renumber_plan, execute_renumbering, get_target_payments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Apply the reviewed plan; default is dry-run")
    parser.add_argument("--resume", type=Path, help="Resume the exact plan in a prior audit JSON")
    parser.add_argument("--fy", default="2025-26")
    parser.add_argument("--source-prefix", default="SBE2627CP-")
    parser.add_argument("--destination-prefix", default="SBE2526CP-")
    parser.add_argument("--width", type=int, default=5)
    parser.add_argument("--starting-sequence", type=int)
    parser.add_argument("--workspace-id", default=os.environ.get("ZOHO_ANALYTICS_WORKSPACE_ID", "264324000000002043"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "output")
    args = parser.parse_args(argv)
    books = get_books_client()
    if args.resume:
        audit_file = args.resume.resolve()
        audit = json.loads(audit_file.read_text(encoding="utf-8"))
        if audit.get("schema_version") != 1:
            raise ValueError("Unsupported audit schema; legacy one-off reports cannot be resumed")
        plan = audit["plan"]
        previous = audit.get("results", [])
    else:
        start, end, fy = get_fy_date_range(args.fy)
        records = get_target_payments(get_analytics_client(), args.workspace_id)
        plan = build_renumber_plan(books, records, source_prefix=args.source_prefix,
                                  destination_prefix=args.destination_prefix, start_date=start,
                                  end_date=end, width=args.width, starting_sequence=args.starting_sequence)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        audit_file = args.output_dir / f"renumber_sbe2627_payments_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        audit = {"schema_version": 1, "generated_at": datetime.now().isoformat(),
                 "financial_year": fy, "plan": plan, "results": []}
        previous = []
    # Keep prior recovery evidence while replacing the current attempt's outcomes.
    audit.setdefault("attempts", []).append({"started_at": datetime.now().isoformat(),
                                             "mode": "execute" if args.execute else "dry-run",
                                             "prior_results": previous})
    audit["mode"] = "execute" if args.execute else "dry-run"

    def checkpoint(results):
        audit["results"] = results
        write_atomic_json(audit_file, audit)

    checkpoint(previous)
    results = execute_renumbering(books, plan, execute=args.execute,
                                 previous_results=previous, checkpoint=checkpoint)
    checkpoint(results)
    for row in plan:
        print(f"{row['current_payment_number']} -> {row['new_payment_number']} ({row['payment_id']})")
    print(f"Audit saved to: {audit_file}")
    if args.execute and (len(results) != len(plan) or any(r["status"] != "verified" for r in results)):
        print("Execution incomplete; inspect the audit and Books before resuming.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
