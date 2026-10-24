"""Check an HDFC CSV for lines missing from the Analytics Books statement table."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from workflows.analytics_catalog import AnalyticsCatalog
from workflows.analytics_catalog.registry import WorkflowViewReference
from workflows.bank_statement_check import (
    DEFAULT_VIEW_ID, DEFAULT_WORKSPACE_ID, comparison_dict, compare_statement_lines,
    fetch_statement_snapshot, parse_analytics_lines, read_hdfc_csv,
)
from workflows.core.auth import get_analytics_client
from workflows.core.checkpoint import atomic_text_writer, write_atomic_json
from workflows.core.config import Config

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--account-id", default=Config.BANK_ACCOUNT_HDFC, help="Books bank account ID (default: configured HDFC)")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--view-id", default=DEFAULT_VIEW_ID)
    parser.add_argument("--catalog-dir", type=Path, help="Cached metadata directory; defaults to workspace_metadata/<workspace-id>")
    parser.add_argument("--saved", type=Path, help="Replay a source snapshot without network access")
    parser.add_argument("--output", type=Path, default=ROOT / "output/hdfc_statement_check")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    inputs = [args.csv.resolve()] + ([args.saved.resolve()] if args.saved else [])
    if any(path == output or output in path.parents for path in inputs):
        parser.error("Output directory must not contain CSV or snapshot inputs")
    lines = read_hdfc_csv(args.csv)
    start, end = min(line.date for line in lines), max(line.date for line in lines)
    if args.saved:
        snapshot = json.loads(args.saved.read_text(encoding="utf-8"))
        expected = {"schema_version": 1, "workspace_id": args.workspace_id, "view_id": args.view_id,
                    "account_id": args.account_id, "start": start.isoformat(), "end": end.isoformat()}
        if any(snapshot.get(key) != value for key, value in expected.items()):
            raise ValueError("Saved snapshot does not match the requested account, table, workspace or CSV period")
    else:
        catalog_dir = args.catalog_dir or ROOT / "workspace_metadata" / args.workspace_id
        reference = WorkflowViewReference("bank_statement_check", "", "src/workflows/bank_statement_check.py", view_id=args.view_id)
        catalog = AnalyticsCatalog(None, args.workspace_id, catalog_dir, references=(reference,))
        # Check cached design before retrieving credentials or making remote reads.
        catalog.analyze(args.view_id)
        snapshot = fetch_statement_snapshot(get_analytics_client(), catalog=catalog,
            account_id=args.account_id, start=start, end=end, view_id=args.view_id)
    books = parse_analytics_lines(snapshot["rows"], account_id=args.account_id, start=start, end=end)
    report = compare_statement_lines(lines, books, account_id=args.account_id)
    output.mkdir(parents=True, exist_ok=True)
    write_atomic_json(output / "sources.json", snapshot)
    write_atomic_json(output / "comparison.json", comparison_dict(report))
    counts = Counter(item.status for item in report.results)
    with atomic_text_writer(output / "exceptions.csv", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["CSV line", "Date", "Direction", "Amount", "Reference", "Narration", "Status", "Reason"])
        for item in report.results:
            if item.status != "matched":
                line = item.line
                writer.writerow([line.source_id, line.date.isoformat(), line.direction, line.amount,
                                 line.reference, line.description, item.status, item.reason])
    with atomic_text_writer(output / "missing.csv", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["CSV line", "Date", "Direction", "Amount", "Reference", "Narration", "Status"])
        for item in report.results:
            if item.status in {"missing", "duplicate_shortfall"}:
                line = item.line
                writer.writerow([line.source_id, line.date, line.direction, line.amount,
                                 line.reference, line.description, item.status])
    md = ["# HDFC statement completeness", "",
          f"Account ID: {args.account_id}; Analytics view: {args.view_id}",
          f"Period: {start} through {end}", f"Data captured (UTC): {snapshot['captured_at']}",
          f"Last successful metadata sync (UTC): {snapshot['last_successful_metadata_sync_at']}", "",
          f"CSV lines: {report.csv_count}; Books statement lines: {report.books_count}",
          f"Unmatched Books statement lines: {len(report.unmatched_books_ids)} (IDs recorded in comparison.json)",
          f"Matched: {counts['matched']}; Probable masked cheques: {counts['probable']}; Missing: {counts['missing']}; Duplicate shortages: {counts['duplicate_shortfall']}; Review: {counts['review']}", "",
          "Missing means absent from the Analytics replica at capture time; source synchronization can lag Books.",
          "Matches require the same posting date, direction and amount plus reference or full narration.",
          "Numeric reference leading zeroes and narration whitespace/case are ignored; numeric account masks in otherwise complete narrations are supported; duplicates consume distinct Books lines.",
          "Duplicate shortages establish a count difference; identical CSV occurrences cannot be individually distinguished.",
          "Probable matches use unique cheque date/direction/amount, full retained narration prefix and masked reference suffix; they need review for full identity certainty.",
          "Review rows share date/direction/amount with Books but lack matching identity and are not confirmed missing.", "",
          "| CSV line | Date | Direction | Amount | Reference | Status | Narration |", "|---|---|---|---:|---|---|---|"]
    def escape(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    priority = {"missing": 0, "duplicate_shortfall": 1, "review": 2, "probable": 3, "matched": 4}
    for item in sorted(report.results, key=lambda result: priority[result.status]):
        if item.status != "matched":
            line = item.line
            md.append("| " + " | ".join(escape(v) for v in (line.source_id, line.date, line.direction,
                f"{line.amount:,.2f}", line.reference, item.status, line.description)) + " |")
    with atomic_text_writer(output / "report.md") as stream:
        stream.write("\n".join(md) + "\n")
    print(json.dumps({"csv_lines": report.csv_count, "books_lines": report.books_count,
                      "counts": dict(counts), "report": str(output / "report.md")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
