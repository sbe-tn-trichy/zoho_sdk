"""Compare a reviewed Google financial statement sheet with Books schedules."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.checkpoint import atomic_text_writer, write_atomic_json
from workflows.financial_statement_comparison import (
    compare_statement_cells, fetch_schedule_reports, read_sheet_cells, render_comparison,
    validate_statement_totals,
)

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=ROOT / "examples/financial_statement_fy2425.mapping.json")
    parser.add_argument("--sheet-snapshot", type=Path, help="Use a captured sheet instead of live Google OAuth")
    parser.add_argument("--saved", action="store_true", help="Use saved Books schedules; no Books network access")
    parser.add_argument("--output", type=Path, default=ROOT / "output/sheet-schedule-comparison")
    parser.add_argument("--tolerance", type=Decimal, default=Decimal("1"))
    args = parser.parse_args(argv)
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    include_opening = any(term.get("period") == "opening" for line in config["lines"] for term in line.get("terms", []))
    if args.saved and not args.sheet_snapshot:
        parser.error("--saved requires --sheet-snapshot for fully offline replay")
    targets = [args.output / name for name in ("report.md", "comparison.json", "sheet-cells.json",
               "scheduleprofitandloss.json", "schedulebalancesheet.json")]
    if include_opening:
        targets.append(args.output / "schedulebalancesheet-opening.json")
    protected = {args.mapping.resolve()}
    if args.sheet_snapshot:
        protected.add(args.sheet_snapshot.resolve())
    # A saved source may be the existing output snapshot, but never overwrite it.
    written = targets[:2] + ([] if args.saved else targets[3:]) + ([] if args.sheet_snapshot else [targets[2]])
    if any(path.resolve() in protected for path in written):
        parser.error("Report outputs must not overwrite input files")
    if args.sheet_snapshot:
        snapshot = json.loads(args.sheet_snapshot.read_text(encoding="utf-8"))
        for key in ("spreadsheet_id", "from_date", "to_date"):
            if snapshot.get(key) != config[key]:
                raise ValueError(f"Sheet snapshot {key} does not match configuration")
        cells = snapshot["cells"]
        provenance = "captured Google cells at " + snapshot["captured_at"]
    else:
        requested_cells = list(dict.fromkeys([line["cell"] for line in config["lines"]] +
            [cell for group in config.get("total_checks", []) for cell in [group["total_cell"], *group["cells"]]]))
        cells = read_sheet_cells(config["spreadsheet_id"], requested_cells,
                                 access_token=os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN", ""))
        provenance = "live Google cells at " + datetime.now(timezone.utc).isoformat()
    validate_statement_totals(cells, config.get("total_checks", []))
    if args.saved:
        names = ["profitandloss", "balancesheet"] + (["balancesheet-opening"] if include_opening else [])
        reports = {name: json.loads((args.output / f"schedule{name}.json").read_text(encoding="utf-8"))
                   for name in names}
        # Use SDK validation against saved responses, including period and scope.
        from zoho.books.resources.reports import Reports
        class SavedClient:
            def request(self, method, endpoint, *, params):
                name = endpoint.removeprefix("reports/schedule")
                if name == "balancesheet" and params["to_date"] != config["to_date"]:
                    name += "-opening"
                return reports[name]
        books = SimpleNamespace(reports=Reports(SavedClient()))
        reports = fetch_schedule_reports(books, from_date=config["from_date"], to_date=config["to_date"],
                                         excluded_location_id=config["excluded_location_id"],
                                         include_opening_balance_sheet=include_opening)
        provenance += "; saved Books schedules (retrieval metadata retained in JSON)"
    else:
        reports = fetch_schedule_reports(get_books_client(), from_date=config["from_date"],
            to_date=config["to_date"], excluded_location_id=config["excluded_location_id"],
            include_opening_balance_sheet=include_opening)
        provenance += "; Books retrieved at " + datetime.now(timezone.utc).isoformat()
    rows = compare_statement_cells(cells, reports, config["lines"], tolerance=args.tolerance)
    if not args.saved:
        for name, report in reports.items():
            target = args.output / f"schedule{name}.json"
            if target.resolve() in protected:
                raise ValueError("Books snapshot output must not overwrite an input")
            write_atomic_json(target, report)
    if not args.sheet_snapshot:
        write_atomic_json(args.output / "sheet-cells.json", {**{key: config[key] for key in
            ("spreadsheet_id", "from_date", "to_date")}, "captured_at": datetime.now(timezone.utc).isoformat(), "cells": cells})
    write_atomic_json(args.output / "comparison.json", [
        {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(row).items()} for row in rows])
    with atomic_text_writer(args.output / "report.md") as handle:
        handle.write(render_comparison(rows, source_url=config["source_url"], from_date=config["from_date"],
                    to_date=config["to_date"], provenance=provenance))
    print(f"{len(rows)} lines: " + ", ".join(f"{status}={sum(r.status == status for r in rows)}" for status in
          ("MATCH", "DIFFERENCE", "UNMAPPED")))
    print((args.output / "report.md").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
