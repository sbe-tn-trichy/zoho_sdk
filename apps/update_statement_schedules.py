"""Preview/apply two-year Books schedule and fixed-asset updates to Google Sheets."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

import yaml

from workflows.core.auth import get_books_client
from workflows.statement_schedules import (
    apply_plan, build_schedule_plan, cell_data, changed_update_requests,
    checkbox_formula_updates, fetch_schedule_sources, grid_address,
    note_bold_requests, update_requests,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/statement-schedules.yaml"


def asset_statement_preview(values: dict[str, list[list[Any]]], config: dict[str, Any]) -> list[str]:
    """Show reviewed A:I output with calculated totals, without a Sheets write."""
    if config.get("asset_layout") != "reviewed_statement":
        return []
    rows = next(rows for address, rows in values.items()
                if grid_address(address)[0] == config["sheets"]["assets"])
    headers = list(rows[1])
    headers[2:4] = ["ADDITIONS Before 30/9", "ADDITIONS After 30/9"]
    lines = ["", "## Assets & Depreciation — sheet output", "", rows[0][0], ""]
    def cell(value: Any) -> str:
        if isinstance(value, Decimal):
            return f"{value:,.2f}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines.extend(["| " + " | ".join(headers) + " |",
                  "| " + " | ".join(["---"] + ["---:"] * 3 + ["---"] + ["---:"] * 4) + " |"])
    totals = [Decimal(0)] * 9
    for row in rows[3:-2]:
        rendered = list(row)
        for c in (1, 2, 3, 7):
            rendered[c] = Decimal(str(row[c])) if row[c] != "" else Decimal(0)
        rendered[5] = sum((rendered[c] for c in (1, 2, 3)), Decimal(0))
        rendered[8] = rendered[5] - rendered[7]
        for c in (1, 2, 3, 5, 7, 8):
            totals[c] += rendered[c]
        rendered[2:4] = [rendered[c] if row[c] != "" else "" for c in (2, 3)]
        lines.append("| " + " | ".join(cell(v) for v in rendered) + " |")
    total = ["Total"] + [totals[c] if c in (1, 2, 3, 5, 7, 8) else "" for c in range(1, 9)]
    lines.append("| " + " | ".join(cell(v) for v in total) + " |")
    return lines


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
    lines.extend(asset_statement_preview(plan.values, config))
    lines.extend(["", "## Depreciation verification", "", "| FY | Asset | Calculated | Posted | Difference |", "| --- | --- | ---: | ---: | ---: |"])
    for label, checks in plan.asset_checks.items():
        for check in checks:
            lines.append(f"| {label} | {check.name.replace('|', '/')} | {check.calculated} | {check.posted} | {check.difference} |")
    lines.extend(["", "## Review observations", "", *["- " + warning for warning in plan.warnings]])
    lines.extend(["", "Configured note and asset ranges are managed blocks. Statement detail values link to note totals; existing statement subtotal formulas remain."])
    (output / "preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.apply:
        config["backup_path"] = str(output / "sheet-before.json")
        apply_plan(config["spreadsheet_id"], plan.values, access_token=os.environ["GOOGLE_SHEETS_ACCESS_TOKEN"], config=config)
        print("Google Sheets update verified by read-back")
    print(f"Preview: {output / 'preview.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
