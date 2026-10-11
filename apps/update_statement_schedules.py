"""Preview/apply two-year Books schedule and fixed-asset updates to Google Sheets."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
from typing import Any

import requests
import yaml

from workflows.core.auth import get_books_client
from workflows.statement_schedules import build_schedule_plan, fetch_schedule_sources

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/statement-schedules.yaml"


def grid_address(address: str) -> tuple[str, int, int, int, int]:
    match = re.fullmatch(r"'((?:[^']|'')+)'!([A-Z]+)([1-9]\d*)(?::([A-Z]+)([1-9]\d*))?", address)
    if match is None:
        raise ValueError(f"Invalid qualified A1 range: {address}")
    def column(text: str) -> int:
        value = 0
        for char in text:
            value = value * 26 + ord(char) - ord("A") + 1
        return value - 1
    name, first_col, first_row, last_col, last_row = match.groups()
    return name.replace("''", "'"), int(first_row) - 1, column(first_col), int(last_row or first_row), column(last_col or first_col) + 1


def cell_data(value: Any, *, literal: bool) -> dict[str, Any]:
    if value == "":
        return {}
    if isinstance(value, (float, int)):
        return {"userEnteredValue": {"numberValue": value}}
    field = "formulaValue" if isinstance(value, str) and value.startswith("=") and not literal else "stringValue"
    return {"userEnteredValue": {field: value}}


def update_requests(values: dict[str, list[list[Any]]], config: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for address, rows in values.items():
        title, first_row, first_col, end_row, end_col = grid_address(address)
        key = next(k for k, name in config["sheets"].items() if name == title)
        if len(rows) != end_row - first_row:
            raise ValueError("Range height does not match rows")
        grid_rows = []
        for row in rows:
            if len(row) > end_col - first_col:
                raise ValueError("Row is wider than target range")
            padded = row + [""] * (end_col - first_col - len(row))
            grid_rows.append({"values": [cell_data(value, literal=(
                (key == "notes" and c + first_col == 0) or
                (key == "assets" and c + first_col in (0, 4, 13, 14))))
                for c, value in enumerate(padded)]})
        result.append({"updateCells": {"range": {
            "sheetId": config["sheet_ids"][key], "startRowIndex": first_row, "endRowIndex": end_row,
            "startColumnIndex": first_col, "endColumnIndex": end_col},
            "rows": grid_rows, "fields": "userEnteredValue"}})
    return result


def apply_plan(spreadsheet_id: str, values: dict[str, list[list[Any]]], *,
               access_token: str, config: dict[str, Any], session: Any = requests) -> None:
    """Verify target layout, snapshot prior cells, batch write and read back formulas.

    Only configured note/asset rectangles and statement detail cells are managed.
    Formatting, validation, and main statement subtotal formulas are preserved.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id) or not access_token:
        raise ValueError("A Google spreadsheet ID and edit token are required")
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    meta = session.get(base, headers=headers, params={"fields": "sheets.properties"}, timeout=30)
    meta.raise_for_status()
    sheets = {s["properties"]["title"]: s["properties"] for s in meta.json()["sheets"]}
    for key, title in config["sheets"].items():
        if title not in sheets or sheets[title]["sheetId"] != config["sheet_ids"][key]:
            raise ValueError(f"Sheet identity changed: {title}")
    values = {key: [list(row) for row in rows] for key, rows in values.items()}
    # Read the configured managed blocks to remove stale generated rows on rerun.
    managed = {}
    for key, last_column in (("notes", "C"), ("assets", "O")):
        title = config["sheets"][key]
        row_limit = min(sheets[title]["gridProperties"]["rowCount"], config.get("managed_row_limit", 500))
        managed[key] = "'" + title.replace("'", "''") + f"'!A1:{last_column}{row_limit}"
    prior = session.get(base + "/values:batchGet", headers=headers,
                        params={"ranges": list(managed.values()), "valueRenderOption": "FORMULA"}, timeout=30)
    prior.raise_for_status()
    prior_ranges = prior.json().get("valueRanges", [])
    if len(prior_ranges) != 2:
        raise ValueError("Could not inspect managed note and asset blocks")
    for key, entry in zip(managed, prior_ranges):
        title = config["sheets"][key]
        address = next(a for a in values if grid_address(a)[0] == title)
        rows = values.pop(address)
        if len(entry.get("values", [])) >= grid_address(managed[key])[3]:
            raise ValueError("Managed rows reach the configured scan limit; increase managed_row_limit")
        height = max(len(rows), len(entry.get("values", [])))
        if height > grid_address(managed[key])[3]:
            raise ValueError("Plan exceeds managed row limit or existing grid")
        width = 3 if key == "notes" else 15
        values["'" + title.replace("'", "''") + f"'!A1:{'C' if width == 3 else 'O'}{height}"] = rows + [[""] * width for _ in range(height - len(rows))]
    requests_body = update_requests(values, config)
    for request in requests_body:
        target = request["updateCells"]["range"]
        sheet = next(s for s in sheets.values() if s["sheetId"] == target["sheetId"])
        if (target["endRowIndex"] > sheet["gridProperties"]["rowCount"] or
                target["endColumnIndex"] > sheet["gridProperties"]["columnCount"]):
            raise ValueError("Plan exceeds the existing sheet grid")
    # Check native validation and formulas before writing, including destinations
    # whose displayed plain values can conceal validation constraints.
    native = session.get(base, headers=headers, params={"ranges": list(values), "includeGridData": "true",
        "fields": "sheets(properties(title),data(startRow,startColumn,rowData(values(userEnteredValue,dataValidation))))"}, timeout=30)
    native.raise_for_status()
    if {s["properties"]["title"] for s in native.json().get("sheets", [])} != set(config["sheets"].values()):
        raise ValueError("Native cell metadata read is incomplete")
    for sheet in native.json().get("sheets", []):
        for grid in sheet.get("data", []):
            for row in grid.get("rowData", []):
                if any(cell.get("dataValidation") for cell in row.get("values", [])):
                    raise ValueError("Managed target contains data validation; review it before apply")
    read = session.get(base + "/values:batchGet", headers=headers,
                       params={"ranges": list(values), "valueRenderOption": "FORMULA"}, timeout=30)
    read.raise_for_status()
    old = read.json().get("valueRanges", [])
    if len(old) != len(values):
        raise ValueError("Google Sheets did not return every target range")
    for address, entry in zip(values, old):
        if ":" not in address and address.split("!")[-1].startswith(("C", "D")):
            existing = (entry.get("values") or [[None]])[0][0]
            note_prefix = "='" + config["sheets"]["notes"].replace("'", "''") + "'!"
            title, row, col, _, _ = grid_address(address)
            is_note_target = any(config["sheets"][n["statement"]] == title and n["statement_row"] == row + 1
                                 for n in config["notes"])
            source_col = "B" if col == 2 else "C"
            managed_note_link = is_note_target and isinstance(existing, str) and re.fullmatch(
                re.escape(note_prefix + source_col) + r"[1-9]\d*", existing)
            if isinstance(existing, str) and existing.startswith("=") and existing != values[address][0][0] and not managed_note_link:
                raise ValueError(f"Unexpected existing formula in {address}")
    # The runner supplies an output path checked before any network call.
    snapshot = Path(config["backup_path"])
    snapshot.write_text(json.dumps(read.json(), indent=2), encoding="utf-8")
    write = session.post(base + ":batchUpdate", headers=headers,
                         json={"requests": requests_body}, timeout=30)
    write.raise_for_status()
    verify = session.get(base + "/values:batchGet", headers=headers,
                         params={"ranges": list(values), "valueRenderOption": "FORMULA"}, timeout=30)
    verify.raise_for_status()
    returned = verify.json().get("valueRanges", [])
    if len(returned) != len(values):
        raise ValueError("Google Sheets read-back is incomplete after update")
    for (address, expected), entry in zip(values.items(), returned):
        actual = entry.get("values", [])
        for r, row in enumerate(expected):
            for c, cell in enumerate(row):
                got = actual[r][c] if r < len(actual) and c < len(actual[r]) else ""
                if got != cell:
                    raise ValueError(f"Google Sheets read-back differs in {address}, row {r + 1}, column {c + 1}")
    effective = session.get(base + "/values:batchGet", headers=headers,
                             params={"ranges": list(values), "valueRenderOption": "UNFORMATTED_VALUE"}, timeout=30)
    effective.raise_for_status()
    for entry in effective.json().get("valueRanges", []):
        for row in entry.get("values", []):
            if any(isinstance(value, str) and value.startswith(("#REF!", "#VALUE!", "#ERROR!", "#DIV/0!", "#NAME?", "#N/A")) for value in row):
                raise ValueError("Google Sheets contains a formula error after update")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--saved", type=Path, help="Replay an exact source snapshot without Books access")
    parser.add_argument("--output", type=Path, default=ROOT / "output/statement-schedules")
    parser.add_argument("--apply", action="store_true", help="Apply the verified plan to Google Sheets")
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8-sig"))
    output = args.output.resolve()
    inputs = [args.config.resolve()] + ([args.saved.resolve()] if args.saved else [])
    if any(path == output or output in path.parents for path in inputs):
        parser.error("Output must not contain configuration or source inputs")
    output.mkdir(parents=True, exist_ok=True)
    if args.apply and not os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN"):
        parser.error("Set GOOGLE_SHEETS_ACCESS_TOKEN with spreadsheet edit scope before --apply")
    sources = (json.loads(args.saved.read_text(encoding="utf-8")) if args.saved else fetch_schedule_sources(
        get_books_client(), periods=config["periods"], excluded_location_id=config["excluded_location_id"],
        include_opening_inventory=bool(config.get("inventory_rollforward"))))
    if sources.get("organization_id") != str(config["organization_id"]):
        raise ValueError("Books organization does not match configuration")
    (output / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    plan = build_schedule_plan(sources, config)
    (output / "plan.json").write_text(json.dumps(asdict(plan), indent=2, default=str), encoding="utf-8")
    lines = ["# Financial statement schedule preview", "", "Two separate annual Schedule III reads per report; accrual basis; configured branch excluded.",
             "", "Source captured at: " + str(sources.get("captured_at", "not recorded in imported snapshot")),
             "", "| FY | Assets | Liabilities | Profit before tax |", "| --- | ---: | ---: | ---: |"]
    for label, check in plan.checks.items():
        lines.append(f"| {label} | {check['assets']} | {check['liabilities']} | {check['profit_before_tax']} |")
    if config.get("inventory_rollforward"):
        lines.extend(["", "## Purchases and inventory movement", "", "Net purchases = COGS − opening stock + closing stock. Changes in inventories = COGS − net purchases.",
                      "", "| FY | COGS | Opening stock | Closing stock | Net purchases | Changes in inventories |",
                      "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for label, check in plan.checks.items():
            lines.append(f"| {label} | {check['cogs']} | {check['opening_stock']} | {check['closing_stock']} | {check['net_purchases']} | {check['changes_in_inventories']} |")
    lines.extend(["", "## Depreciation verification", "", "| FY | Asset | Calculated | Posted | Difference |", "| --- | --- | ---: | ---: | ---: |"])
    for label, checks in plan.asset_checks.items():
        for check in checks:
            lines.append(f"| {label} | {check.name.replace('|', '/')} | {check.calculated} | {check.posted} | {check.difference} |")
    lines.extend(["", "## Review observations", "", *["- " + warning for warning in plan.warnings]])
    lines.extend(["", "Notes A:C and Assets & Depreciation A:O are managed blocks. Statement detail values link to note totals; existing statement subtotal formulas remain."])
    (output / "preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.apply:
        config["backup_path"] = str(output / "sheet-before.json")
        apply_plan(config["spreadsheet_id"], plan.values, access_token=os.environ["GOOGLE_SHEETS_ACCESS_TOKEN"], config=config)
        print("Google Sheets update verified by read-back")
    print(f"Preview: {output / 'preview.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
