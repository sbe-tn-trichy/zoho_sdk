"""Preview or apply mapped Zoho Books report amounts to a Google Sheet.

Mapping JSON contains an array of objects with report, sheet, current_cell,
previous_cell, and either source_path (array of JSON keys/indexes) or
account_ids (stable Zoho Books account IDs). Optional multiplier is a decimal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal
from pathlib import Path

import requests

from workflows.books_statement_sheet import StatementMapping, StatementPeriod, prepare_updates
from workflows.core.auth import get_books_client


SPREADSHEET_ID = "1uJanzAcLO4S5K0079I5KiVNHAUpmmm2PS4MveTqq3uU"
CELL = re.compile(r"^[A-Z]+[1-9][0-9]*$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path, help="Reviewed JSON cell-to-report mapping")
    parser.add_argument("--apply", action="store_true", help="Write after preview and formula checks")
    parser.add_argument("--spreadsheet-id", default=SPREADSHEET_ID)
    args = parser.parse_args(argv)
    raw = json.loads(args.mapping.read_text(encoding="utf-8"))
    mappings = [StatementMapping(
        report=item["report"], source_path=tuple(item.get("source_path", ())),
        sheet=item["sheet"], current_cell=item["current_cell"],
        previous_cell=item["previous_cell"], multiplier=Decimal(str(item.get("multiplier", 1))),
        account_ids=tuple(str(value) for value in item.get("account_ids", ())),
    ) for item in raw]
    if not mappings:
        parser.error("Mapping cannot be empty")
    for item in mappings:
        if not CELL.fullmatch(item.current_cell) or not CELL.fullmatch(item.previous_cell):
            parser.error("Mappings must use single-cell A1 addresses")
    periods = StatementPeriod("2025-04-01", "2026-03-31", "2024-04-01", "2025-03-31")
    updates = prepare_updates(get_books_client(), periods, mappings)
    print(json.dumps({key: str(value) for key, value in updates.items()}, indent=2))
    if not args.apply:
        return 0
    token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
    if not token:
        parser.error("Set GOOGLE_SHEETS_ACCESS_TOKEN with spreadsheet edit scope before --apply")
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{args.spreadsheet_id}/values:batchGet"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(base, headers=headers, params={"ranges": list(updates), "valueRenderOption": "FORMULA"}, timeout=30)
    response.raise_for_status()
    for entry in response.json().get("valueRanges", []):
        old = (entry.get("values") or [[None]])[0][0]
        if isinstance(old, str) and old.startswith("="):
            raise ValueError(f"Refusing to overwrite formula in {entry['range']}")
    body = {"valueInputOption": "RAW", "data": [
        {"range": address, "values": [[float(value)]]} for address, value in updates.items()
    ]}
    response = requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{args.spreadsheet_id}/values:batchUpdate",
        headers=headers, json=body, timeout=30,
    )
    response.raise_for_status()
    print(f"Updated {response.json().get('totalUpdatedCells', 0)} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
