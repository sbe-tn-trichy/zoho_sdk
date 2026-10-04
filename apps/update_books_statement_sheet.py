"""Preview or apply mapped Zoho Books report amounts to a Google Sheet.

Configuration YAML or JSON contains ``spreadsheet_id``, a non-empty ``location_ids``
array, and a ``mappings`` array. Each mapping has report, sheet, current_cell,
previous_cell, and either source_path (an array of JSON keys/indexes) or
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
import yaml
import yaml

from workflows.books_statement_sheet import (
    EquityMapping,
    StatementMapping,
    StatementPeriod,
    prepare_equity_updates,
    prepare_updates,
)
from workflows.books_account_catalog import (
    refresh_mapping_account_names,
    sync_account_catalog,
    write_mapping_config,
)
from workflows.core.auth import get_books_client
from workflows.books_pnl_notes import NOTE_INPUTS, NOTE_SHEET, prepare_pnl_note_updates


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAPPING = PROJECT_ROOT / "config" / "accounting-mapping.yaml"
DEFAULT_ACCOUNT_DB = PROJECT_ROOT / "output" / "books_accounts.sqlite3"
CELL = re.compile(r"^[A-Z]+[1-9][0-9]*$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping",
        type=Path,
        nargs="?",
        default=DEFAULT_MAPPING,
        help=f"Reviewed YAML or JSON cell-to-report mapping (default: {DEFAULT_MAPPING})",
    )
    parser.add_argument("--apply", action="store_true", help="Write after preview and formula checks")
    parser.add_argument("--equity-only", action="store_true", help="Preview or update only the equity note")
    parser.add_argument("--pnl-only", action="store_true", help="Preview or update only FY P&L note inputs")
    parser.add_argument("--partner-interest", type=Decimal, help="Override Note 3 partner interest for a P&L preview")
    parser.add_argument("--spreadsheet-id", help="Override the spreadsheet ID in the JSON")
    parser.add_argument(
        "--accounts-db",
        type=Path,
        default=DEFAULT_ACCOUNT_DB,
        help="SQLite chart-of-accounts snapshot",
    )
    args = parser.parse_args(argv)
    if not args.mapping.is_file():
        parser.error(
            f"Mapping file not found: {args.mapping}. Copy "
            "config/accounting-mapping.example.yaml to "
            f"{DEFAULT_MAPPING} and review its account IDs and cells."
        )
    text = args.mapping.read_text(encoding="utf-8")
    try:
        config = (yaml.safe_load(text) if args.mapping.suffix.lower() in {".yaml", ".yml"}
                  else json.loads(text))
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        parser.error(f"Invalid mapping configuration: {exc}")
    if not isinstance(config, dict):
        parser.error("Mapping configuration must be an object with spreadsheet_id and mappings")
    spreadsheet_id = args.spreadsheet_id or config.get("spreadsheet_id")
    if not isinstance(spreadsheet_id, str) or not spreadsheet_id.strip():
        parser.error("Mapping configuration must contain a non-empty spreadsheet_id")
    location_ids = config.get("location_ids")
    if (not isinstance(location_ids, list) or not location_ids
            or any(not isinstance(value, str) or not value.strip() for value in location_ids)):
        parser.error("Mapping configuration must contain a non-empty location_ids array")
    raw = config.get("mappings")
    if not isinstance(raw, list):
        parser.error("Mapping configuration must contain a mappings array")
    if args.pnl_only:
        if args.equity_only:
            parser.error("Choose --pnl-only or --equity-only")
        pnl = config.get("pnl_notes")
        if not isinstance(pnl, dict) or pnl.get("sheet") != NOTE_SHEET:
            parser.error("Mapping configuration needs pnl_notes with the reviewed note sheet")
        token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
        if args.apply and not token:
            parser.error("Set GOOGLE_SHEETS_ACCESS_TOKEN before --apply")
        partner_interest = args.partner_interest
        base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if partner_interest is None or args.apply:
            if not token:
                parser.error("Provide --partner-interest for a preview or set GOOGLE_SHEETS_ACCESS_TOKEN")
            response = requests.get(base_url, headers=headers, params={
                "ranges": [pnl["partner_interest_cell"]], "valueRenderOption": "UNFORMATTED_VALUE",
            }, timeout=30)
            response.raise_for_status()
            try:
                partner_interest = Decimal(str(response.json()["valueRanges"][0]["values"][0][0]))
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("Could not read partner interest from Note 3") from exc
        updates = prepare_pnl_note_updates(
            get_books_client(), from_date=pnl["current_start"], to_date=pnl["current_end"],
            excluded_location_id=pnl["excluded_location_id"],
            account_groups=pnl["account_groups"], partner_interest=partner_interest,
        )
        if set(updates) != {f"'{NOTE_SHEET}'!{cell}" for cell in NOTE_INPUTS}:
            raise ValueError("P&L note targets differ from reviewed mapping")
        print(json.dumps({key: str(value) for key, value in updates.items()}, indent=2))
        if not args.apply:
            return 0
        response = requests.get(base_url, headers=headers, params={
            "ranges": list(updates), "valueRenderOption": "FORMULA",
        }, timeout=30)
        response.raise_for_status()
        value_ranges = response.json().get("valueRanges", [])
        if len(value_ranges) != len(updates):
            raise ValueError("Could not verify every P&L note input cell")
        for entry in value_ranges:
            old = (entry.get("values") or [[None]])[0][0]
            if isinstance(old, str) and old.startswith("="):
                raise ValueError(f"Refusing to overwrite formula in {entry['range']}")
        body = {"valueInputOption": "RAW", "data": [
            {"range": address, "values": [[float(value)]]}
            for address, value in updates.items()
        ]}
        response = requests.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate",
            headers=headers, json=body, timeout=30,
        )
        response.raise_for_status()
        print(f"Updated {response.json().get('totalUpdatedCells', 0)} P&L note cells")
        return 0
    equity_config = config.get("equity")
    if equity_config is not None and not isinstance(equity_config, dict):
        parser.error("equity must be an object")
    if args.equity_only and equity_config is None:
        parser.error("Mapping configuration must contain equity for --equity-only")
    equity_mappings: list[EquityMapping] = []
    if equity_config is not None:
        if (not isinstance(equity_config.get("movement_header_cell"), str)
                or not CELL.fullmatch(equity_config["movement_header_cell"])):
            parser.error("equity.movement_header_cell must be a single-cell A1 address")
        if (not isinstance(equity_config.get("movement_header"), str)
                or not equity_config["movement_header"].strip()):
            parser.error("equity.movement_header is required")
        if (not isinstance(equity_config.get("interest_account_id"), str)
                or not equity_config["interest_account_id"].strip()):
            parser.error("equity.interest_account_id is required")
        withdrawal_types = equity_config.get("withdrawal_transaction_types")
        if (not isinstance(withdrawal_types, list) or not withdrawal_types
                or any(not isinstance(value, str) or not value.strip() for value in withdrawal_types)):
            parser.error("equity.withdrawal_transaction_types must be a non-empty string array")
        raw_equity = equity_config.get("mappings")
        if not isinstance(raw_equity, list) or not raw_equity:
            parser.error("equity.mappings must be a non-empty array")
        for item in raw_equity:
            if not isinstance(item, dict):
                parser.error("Every equity mapping must be an object")
            mapping = EquityMapping(
                account_id=str(item["account_id"]), sheet=str(item["sheet"]),
                name_cell=str(item["name_cell"]), opening_cell=str(item["opening_cell"]),
                interest_cell=str(item["interest_cell"]), withdrawal_cell=str(item["withdrawal_cell"]),
                movement_cell=str(item["movement_cell"]), closing_cell=str(item["closing_cell"]),
            )
            if any(not CELL.fullmatch(cell) for cell in (
                mapping.name_cell, mapping.opening_cell, mapping.interest_cell,
                mapping.withdrawal_cell, mapping.movement_cell, mapping.closing_cell,
            )):
                parser.error("Equity mappings must use single-cell A1 addresses")
            equity_mappings.append(mapping)
        if not isinstance(equity_config.get("excluded_location_id"), str) or not equity_config["excluded_location_id"].strip():
            parser.error("equity.excluded_location_id is required")
    books = get_books_client()
    catalog_params = {
        "filter_by": "TransactionDate.CustomDate",
        "from_date": "2025-04-01",
        "to_date": "2026-03-31",
        "cash_based": "false",
        "show_rows": "all",
        "location_ids": ",".join(location_ids),
    }
    account_names = sync_account_catalog(
        books,
        args.accounts_db,
        report_params=catalog_params,
        reports=tuple(dict.fromkeys(
            (["balancesheet"] if equity_mappings else []) +
            ([] if args.equity_only else [str(item.get("report") or "") for item in raw if isinstance(item, dict)])
        )),
    )
    if refresh_mapping_account_names(config, account_names):
        write_mapping_config(args.mapping, config)
        raw = config["mappings"]
    mappings = [StatementMapping(
        report=item["report"], source_path=tuple(item.get("source_path", ())),
        sheet=item["sheet"], current_cell=item["current_cell"],
        previous_cell=item["previous_cell"], multiplier=Decimal(str(item.get("multiplier", 1))),
        account_ids=tuple(str(value) for value in item.get("account_ids", ())),
    ) for item in raw]
    if not mappings and not args.equity_only:
        parser.error("Mapping cannot be empty")
    for item in mappings:
        if not CELL.fullmatch(item.current_cell) or not CELL.fullmatch(item.previous_cell):
            parser.error("Mappings must use single-cell A1 addresses")
    periods = StatementPeriod("2025-04-01", "2026-03-31", "2024-04-01", "2025-03-31")
    updates: dict[str, Decimal | str] = (
        {} if args.equity_only else prepare_updates(books, periods, mappings, location_ids)
    )
    if equity_mappings:
        equity_updates = prepare_equity_updates(
            books, periods, equity_mappings, location_ids=location_ids,
            excluded_location_id=equity_config["excluded_location_id"],
            account_names=account_names,
            interest_account_id=equity_config["interest_account_id"],
            withdrawal_transaction_types=tuple(withdrawal_types),
        )
        duplicate = set(updates) & set(equity_updates)
        if duplicate:
            raise ValueError(f"Duplicate target cells: {', '.join(sorted(duplicate))}")
        updates.update(equity_updates)
        header_sheets = {item.sheet for item in equity_mappings}
        if len(header_sheets) != 1:
            raise ValueError("Equity mappings must target one sheet")
        header_sheet = next(iter(header_sheets))
        header_target = f"'{header_sheet.replace(chr(39), chr(39) * 2)}'!{equity_config['movement_header_cell']}"
        if header_target in updates or header_target in {
            f"'{item.sheet.replace(chr(39), chr(39) * 2)}'!{item.closing_cell}"
            for item in equity_mappings
        }:
            raise ValueError(f"Duplicate equity header cell: {header_target}")
        updates[header_target] = equity_config["movement_header"]
    print(json.dumps({key: str(value) for key, value in updates.items()}, indent=2))
    if not args.apply:
        return 0
    token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
    if not token:
        parser.error("Set GOOGLE_SHEETS_ACCESS_TOKEN with spreadsheet edit scope before --apply")
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet"
    headers = {"Authorization": f"Bearer {token}"}
    closing_cells = {
        f"'{item.sheet.replace(chr(39), chr(39) * 2)}'!{item.closing_cell}"
        for item in equity_mappings
    }
    response = requests.get(base, headers=headers, params={"ranges": list(updates) + sorted(closing_cells), "valueRenderOption": "FORMULA"}, timeout=30)
    response.raise_for_status()
    seen_closing: set[str] = set()
    for entry in response.json().get("valueRanges", []):
        old = (entry.get("values") or [[None]])[0][0]
        address = entry["range"]
        if address in closing_cells:
            seen_closing.add(address)
            if not isinstance(old, str) or not old.startswith("="):
                raise ValueError(f"Expected closing-balance formula in {address}")
        elif isinstance(old, str) and old.startswith("="):
            raise ValueError(f"Refusing to overwrite formula in {entry['range']}")
    if seen_closing != closing_cells:
        raise ValueError("Could not verify all equity closing-balance formulas")
    body = {"valueInputOption": "RAW", "data": [
        {"range": address, "values": [[float(value) if isinstance(value, Decimal) else value]]}
        for address, value in updates.items()
    ]}
    response = requests.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate",
        headers=headers, json=body, timeout=30,
    )
    response.raise_for_status()
    print(f"Updated {response.json().get('totalUpdatedCells', 0)} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
