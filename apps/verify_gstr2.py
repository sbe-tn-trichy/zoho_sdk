#!/usr/bin/env python3
"""Cross-check GSTR-2 / GSTR-2B JSON returns against Zoho Books purchases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.gstr2_verification import (
    AggregatePurchaseMapping,
    GSTR2VerificationConfig,
    GSTR2Verifier,
    render_markdown_report,
    verify_gstr2,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "json_file",
        nargs="?",
        default=r"C:\Users\VAK\Downloads\returns_R2B_33AATFB2164K1Z9_042025.json",
        help="Path to the GSTR-2 / GSTR-2B JSON file",
    )
    parser.add_argument(
        "--json-path",
        dest="explicit_json_path",
        help="Explicit path to GSTR-2 / GSTR-2B JSON file (overrides positional)",
    )
    parser.add_argument(
        "--month",
        help="Target month 'YYYY-MM' (if omitted, extracted from JSON return period)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="Amount difference tolerance in INR (default: 1.00)",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include draft bills from Zoho Books in reconciliation",
    )
    parser.add_argument(
        "--org-id",
        default=Config.ORG_ID,
        help="Zoho Books organization ID",
    )
    parser.add_argument(
        "--domain",
        default=Config.DOMAIN,
        help="Zoho data-center domain",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional exact monthly report path (default: Output/GSTR2 Verification/monthly/YYYY-MM.md)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("Output") / "GSTR2 Verification",
        help="Root directory for monthly and cumulative GSTR-2 outputs",
    )
    parser.add_argument(
        "--lookup",
        help="Search Zoho Books for item HSN/SAC, bills, or credits matching a query (e.g. DA2524)",
    )
    parser.add_argument(
        "--aggregate-map",
        type=Path,
        default=Path("output/gstr2_aggregate_mappings.json"),
        help="Local JSON file of approved consolidated purchase mappings",
    )
    return parser


CUMULATIVE_CATEGORIES = {
    "Value Mismatches.csv": "value_mismatches",
    "Missing in Books.csv": "missing_in_books",
    "Missing in GSTR2B - Bills.csv": "missing_in_gstr2_bills",
    "Missing in GSTR2B - Credits.csv": "missing_in_gstr2_credits",
    "Missing in GSTR2B - Expenses.csv": "missing_in_gstr2_expenses",
    "Zero Tax Bills.csv": "zero_tax_bills",
    "Ineligible ITC.csv": "ineligible_itc_documents",
    "Reverse Charge.csv": "rcm_documents",
    "Reconciled Purchases.csv": "matched_documents",
    "Aggregate Matches.csv": "aggregate_matches",
    "Aggregate Warnings.csv": "aggregate_warnings",
    "Vendor Summaries.csv": "vendor_summaries",
}


def _flatten_row(value: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten reconciliation records into readable CSV columns."""
    flattened: dict[str, str] = {}
    for key, item in value.items():
        if key in {"raw", "parsed_date"}:
            continue
        column = f"{prefix}{key}"
        if isinstance(item, Mapping):
            flattened.update(_flatten_row(item, f"{column}."))
        elif isinstance(item, (list, tuple, set)):
            flattened[column] = "; ".join(str(entry) for entry in item)
        else:
            flattened[column] = "" if item is None else str(item)
    return flattened


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "month" not in reader.fieldnames:
                raise ValueError("missing month column")
            rows = list(reader)
            if any(None in row for row in rows):
                raise ValueError("row has more cells than headers")
            return rows
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        raise ValueError(f"Unable to update cumulative output {path}: {exc}") from exc


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Atomically write a month-keyed CSV history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["month", *sorted({key for row in rows for key in row if key != "month"})]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _legacy_rows(path: Path) -> list[dict[str, str]]:
    """Read existing JSON history once so it can be migrated to CSV."""
    if not path.is_file():
        return []
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(history, dict):
            raise ValueError("history must be an object")
        return [
            {"month": month, **_flatten_row(record)}
            for month, records in history.items()
            for record in (records if isinstance(records, list) else [records])
            if isinstance(record, Mapping)
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Unable to migrate cumulative output {path}: {exc}") from exc


def write_reconciliation_outputs(
    result: Mapping[str, Any],
    report_md: str,
    output_root: Path,
    monthly_override: Optional[Path] = None,
) -> tuple[Path, tuple[Path, ...]]:
    """Upsert one monthly report and month-keyed cumulative category files."""
    target_month = str(result["metadata"]["target_month"])
    monthly_path = monthly_override or output_root / "monthly" / f"{target_month}.md"
    reconciliation = result["reconciliation"]
    cumulative_dir = output_root / "cumulative"
    updates: list[tuple[Path, list[dict[str, str]], Path]] = []
    for filename, result_key in CUMULATIVE_CATEGORIES.items():
        path = cumulative_dir / filename
        legacy = path.with_suffix(".json")
        existing = _read_csv(path) if path.exists() else _legacy_rows(legacy)
        current = [{"month": target_month, **_flatten_row(row)}
                   for row in reconciliation.get(result_key, [])]
        updates.append((path, sorted(
            [row for row in existing if row["month"] != target_month] + current,
            key=lambda row: row["month"],
        ), legacy))

    summary_path = cumulative_dir / "Monthly Summaries.csv"
    legacy_summary = summary_path.with_suffix(".json")
    existing = _read_csv(summary_path) if summary_path.exists() else _legacy_rows(legacy_summary)
    summary = {"month": target_month, **_flatten_row(reconciliation.get("summary", {}))}
    updates.append((summary_path, sorted(
        [row for row in existing if row["month"] != target_month] + [summary],
        key=lambda row: row["month"],
    ), legacy_summary))

    monthly_path.parent.mkdir(parents=True, exist_ok=True)
    monthly_path.write_text(report_md, encoding="utf-8")
    for path, rows, _ in updates:
        _write_csv(path, rows)
    for _, _, legacy in updates:
        legacy.unlink(missing_ok=True)
    return monthly_path, tuple(path for path, _, _ in updates)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    print("Connecting to Zoho Books...")
    books = get_books_client(org_id=args.org_id, domain=args.domain)

    if args.lookup:
        print(f"\nLooking up HSN / line items for '{args.lookup}' in Zoho Books...")
        verifier = GSTR2Verifier(books)
        lookup_result = verifier.lookup_hsn(args.lookup)
        
        found = False
        if lookup_result["bills"]:
            found = True
            print("\n=== MATCHING BILLS ===")
            for b in lookup_result["bills"]:
                print(f"Bill #{b['bill_number']} | Date: {b['date']} | Total: Rs. {b['total']} | Vendor: {b['vendor_name']}")
                for it in b["items"]:
                    print(f"  -> Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']} | Tax: {it['tax_name']} ({it['tax_percentage']}%)")

        if lookup_result["vendor_credits"]:
            found = True
            print("\n=== MATCHING VENDOR CREDITS ===")
            for c in lookup_result["vendor_credits"]:
                print(f"Credit #{c['credit_number']} | Ref: {c['reference_number']} | Date: {c['date']} | Total: Rs. {c['total']} | Vendor: {c['vendor_name']}")
                for it in c["items"]:
                    print(f"  -> Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if lookup_result["contacts"]:
            found = True
            print("\n=== MATCHING VENDORS / CONTACTS ===")
            for ct in lookup_result["contacts"]:
                print(f"Vendor: {ct['contact_name']} | GSTIN: {ct['gst_no']} | Bills in Books: {ct['bills_count']}")
                for it in ct["sample_items"]:
                    print(f"  -> Bill #{it['bill_number']} ({it['date']}): {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if lookup_result["items"]:
            found = True
            print("\n=== MATCHING ITEMS IN CATALOG ===")
            for it in lookup_result["items"]:
                print(f"Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if not found:
            print(f"No records or items found matching '{args.lookup}' in Zoho Books.")
        return 0

    json_path = args.explicit_json_path or args.json_file
    if not json_path:
        print("Error: Please provide a GSTR-2B JSON file or directory path.", file=sys.stderr)
        return 1

    path_obj = Path(json_path)
    if not path_obj.exists():
        print(f"Error: Path not found at '{path_obj}'", file=sys.stderr)
        return 1

    mappings = ()
    if args.aggregate_map.is_file():
        try:
            entries = json.loads(args.aggregate_map.read_text(encoding="utf-8"))
            mappings = tuple(AggregatePurchaseMapping(
                **{**entry, "supplier_gstins": tuple(entry["supplier_gstins"])}
            ) for entry in entries)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"Error loading aggregate map: {exc}", file=sys.stderr)
            return 1

    config = GSTR2VerificationConfig(
        amount_tolerance=args.tolerance,
        include_drafts=args.include_drafts,
        aggregate_mappings=mappings,
        location_gstin_map=Config.GSTR2_LOCATION_GSTIN_MAP,
    )

    # Collect items/files to process
    items_to_process: list[tuple[str, Path | Mapping[str, Any]]] = []
    if path_obj.is_dir():
        candidate_files = list(path_obj.glob("*.json"))
        # Parse return periods to sort chronologically and filter out non-return files
        parsed_candidates = []
        for cf in candidate_files:
            try:
                data = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    prd = str(data.get("rtnprd") or (data.get("data", {}).get("rtnprd") if isinstance(data.get("data"), dict) else "") or "")
                    if len(prd) == 6 and prd.isdigit():
                        sort_key = (int(prd[2:6]), int(prd[0:2]))
                    else:
                        sort_key = (9999, 99)
                    parsed_candidates.append((sort_key, cf.name, cf))
                elif isinstance(data, list) and not candidate_files:
                    # If only combined files exist
                    pass
            except Exception:
                continue

        parsed_candidates.sort(key=lambda x: (x[0], x[1]))
        for _, name, cf in parsed_candidates:
            items_to_process.append((name, cf))

        if not items_to_process:
            print(f"Error: No valid GSTR-2B return JSON files found in '{path_obj}'", file=sys.stderr)
            return 1
    else:
        # Check if single file is a combined list
        try:
            raw = json.loads(path_obj.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for idx, elem in enumerate(raw, 1):
                    prd = str(elem.get("rtnprd") or (elem.get("data", {}).get("rtnprd") if isinstance(elem.get("data"), dict) else "") or f"item_{idx}")
                    items_to_process.append((f"{path_obj.name} [{prd}]", elem))
            else:
                items_to_process.append((path_obj.name, path_obj))
        except Exception:
            items_to_process.append((path_obj.name, path_obj))

    total = len(items_to_process)
    print(f"Found {total} return(s) to process.")

    verifier = GSTR2Verifier(books, config=config)
    exit_code = 0
    for idx, (label, source) in enumerate(items_to_process, 1):
        print(f"\n{'=' * 70}")
        print(f"[{idx}/{total}] Processing: {label}")
        print(f"{'=' * 70}")

        result = verifier.run(
            gstr2_source=source,
            month=args.month,
        )

        critical_fetch_errors = [
            error for error in result.get("fetch_errors", [])
            if error.get("source") in {"locations", "bills", "expenses", "vendor_credits"}
        ]
        if critical_fetch_errors:
            for error in critical_fetch_errors:
                print(f"Error fetching {error['source']}: {error['error']}", file=sys.stderr)
            print("Reconciliation incomplete; existing report was not overwritten.", file=sys.stderr)
            exit_code = 1
            continue

        report_md = render_markdown_report(result)
        try:
            monthly_path, cumulative_paths = write_reconciliation_outputs(
                result,
                report_md,
                output_root=args.output_root,
                monthly_override=args.output if total == 1 else None,
            )
        except (OSError, ValueError) as exc:
            print(f"Error writing reconciliation outputs: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        print(f"Monthly report written to: {monthly_path.resolve()}")
        print(f"Cumulative files updated in: {cumulative_paths[0].parent.resolve()}")

        meta = result["metadata"]
        rec = result["reconciliation"]
        summary = rec["summary"]

        print(f"Target Month:          {meta['target_month']} (Return Period: {meta['return_period']})")
        print(f"GSTR-2B Documents:     {summary['gstr2_total_docs']} (Total Value: Rs. {summary['gstr2_total_value']:,.2f})")
        print(f"GSTR-2B Eligible ITC:  Rs. {summary['gstr2_total_tax']:,.2f}")
        print(f"Matched Purchases:     {summary['matched_count']} (ITC: Rs. {summary['matched_tax']:,.2f})")
        print(f"Value Mismatches:      {summary['value_mismatch_count']}")
        print(f"Missing in Books:      {summary['missing_in_books_count']} (Portal ITC: Rs. {summary['missing_in_books_tax']:,.2f})")
        print(f"Missing in GSTR-2B:    {summary['missing_in_gstr2_bills_count']} bills, {summary['missing_in_gstr2_expenses_count']} expenses")
        time.sleep(2.5)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
