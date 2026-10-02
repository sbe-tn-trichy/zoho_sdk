#!/usr/bin/env python3
"""Compare the filed FY 2024-25 balance sheet with Zoho Books."""

from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

import requests

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.it_balance_sheet_comparison import (
    BalanceSheetLine, compare_balance_sheet, write_comparison_csv,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_filed_cells(config: dict, snapshot_path: Path, live_sheet: bool) -> dict:
    if not live_sheet:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        for key in ("spreadsheet_id", "sheet_name", "as_of_date"):
            if snapshot.get(key) != config[key]:
                raise ValueError(f"Filed snapshot {key} does not match mapping")
        return snapshot["cells"]
    token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
    if not token:
        raise ValueError("Set GOOGLE_SHEETS_ACCESS_TOKEN to read the live filed sheet")
    cells = [item["filed_cell"] for item in config["lines"]]
    sheet = config["sheet_name"].replace("'", "''")
    ranges = [f"'{sheet}'!{cell}" for cell in cells]
    response = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{config['spreadsheet_id']}/values:batchGet",
        headers={"Authorization": f"Bearer {token}"},
        params={"ranges": ranges, "valueRenderOption": "UNFORMATTED_VALUE"},
        timeout=30,
    )
    response.raise_for_status()
    entries = response.json().get("valueRanges", [])
    if len(entries) != len(cells):
        raise ValueError("Google Sheets did not return every filed cell")
    return {cell: entry["values"][0][0] for cell, entry in zip(cells, entries)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=REPO_ROOT / "examples/it_balance_sheet_fy2425.mapping.json")
    parser.add_argument("--filed-snapshot", type=Path, default=REPO_ROOT / "output/it_balance_sheet_fy2425.source.json")
    parser.add_argument("--live-sheet", action="store_true", help="Read current cells with Google Sheets OAuth")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output/it_balance_sheet_fy2425_vs_books.csv")
    parser.add_argument("--tolerance", type=Decimal, default=Decimal("1.00"))
    args = parser.parse_args(argv)
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    lines = [BalanceSheetLine(
        label=item["label"], filed_cell=item["filed_cell"],
        account_ids=tuple(item.get("account_ids", ())),
        books_path=tuple(item.get("books_path", ())),
        books_paths=tuple(tuple(path) for path in item.get("books_paths", ())),
    ) for item in config["lines"]]
    filed = _load_filed_cells(config, args.filed_snapshot, args.live_sheet)
    rule = {"columns": [{"index": 1, "field": "location_name",
             "value": [config["excluded_location_id"]], "comparator": "not_in", "group": "branch"}],
            "criteria_string": "1"}
    as_of_date = config["as_of_date"]
    report = get_books_client().request("GET", "reports/balancesheet", params={
        "filter_by": "TransactionDate.CustomDate", "from_date": f"{int(as_of_date[:4])-1}-04-01",
        "to_date": as_of_date, "cash_based": "false", "show_rows": "all",
        "is_expand": "true", "rule": json.dumps(rule, separators=(",", ":")),
    })
    applied = report.get("page_context", {}).get("rule", {})
    if (applied.get("criteria_string") != "1"
            or len(applied.get("columns", [])) != 1
            or any(applied["columns"][0].get(key) != rule["columns"][0][key]
                   for key in ("field", "value", "comparator", "group"))):
        raise ValueError("Books did not echo the requested branch exclusion")
    rows = compare_balance_sheet(report, to_date=as_of_date, filed_cells=filed,
                                 lines=lines, tolerance=args.tolerance)
    write_comparison_csv(rows, args.output)
    print(f"Wrote {len(rows)} comparisons to {args.output}")
    for row in rows:
        print(f"{row.status:10} {row.label}: filed={row.filed} Books={row.books} difference={row.difference}")
    print("Scope check: Books echoed the branch rule; review location-specific balances because its balance-sheet response may still include SBE accounts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
