"""Compare audited XLSX statements with accrual Zoho Books reports (read-only)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import InvalidOperation
import json
import os
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.audited_financials import (
    ComparisonPeriod, compare_audited_financials, fetch_comparison_reports,
    load_accounting_mapping, read_audited_workbook,
)
from workflows.core.auth import get_books_client
from workflows.core.checkpoint import atomic_text_writer, write_atomic_json

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Audited XLSX in the reviewed column-B template")
    parser.add_argument("--mapping", type=Path, default=ROOT / "config/accounting-mapping.yaml")
    parser.add_argument("--from-date", default="2024-04-01")
    parser.add_argument("--to-date", default="2025-03-31")
    parser.add_argument("--exclude-location", action="append", default=None, help="Repeat for each excluded Books location ID; overrides configured firm scope")
    parser.add_argument("--firm", default=None, help="Firm alias or GSTIN from firm-reports.yaml; defaults to configured firm")
    parser.add_argument("--firm-config", type=Path, default=None)
    parser.add_argument("--saved", action="store_true", help="Use saved JSON only; no authentication or network access")
    parser.add_argument("--snapshots", type=Path, default=ROOT / "output/bd-it-fy2425")
    parser.add_argument("--output", type=Path, default=None, help="Markdown destination; defaults to snapshots/audited-financials-vs-books-fy24-25.md")
    args = parser.parse_args(argv)
    try:
        period = ComparisonPeriod(args.from_date, args.to_date)
        mapping = load_accounting_mapping(args.mapping)
        sheets = read_audited_workbook(args.source)
        if args.saved:
            if args.exclude_location is not None or args.firm is not None or args.firm_config is not None:
                raise ValueError("Saved mode uses original snapshot scope; location overrides require a live run")
            names = ("profitandloss", "balancesheet", "trialbalance",
                     "profitandloss-all-locations", "balancesheet-all-locations")
            reports = {name: json.loads((args.snapshots / f"{name}.json").read_text(encoding="utf-8-sig")) for name in names}
            description = "saved API responses; original retrieval times are in each snapshot page_context"
        else:
            excluded = args.exclude_location
            reports = fetch_comparison_reports(get_books_client(), period,
                tuple(excluded) if excluded is not None else None,
                firm=args.firm, firm_config=args.firm_config)
            description = "retrieved " + datetime.now(timezone.utc).isoformat()
        result = compare_audited_financials(sheets, reports, mapping, period,
            source_name=args.source.name, snapshot_description=description)
        destination = args.output or args.snapshots / "audited-financials-vs-books-fy24-25.md"
        protected = {args.source.resolve(), args.mapping.resolve()}
        snapshot_paths = {name: args.snapshots / f"{name}.json" for name in reports}
        targets = {destination.resolve(), (args.snapshots / "audited-cells.json").resolve()}
        targets.update(path.resolve() for path in snapshot_paths.values())
        if protected & targets or destination.resolve() in {path.resolve() for path in snapshot_paths.values()} or destination.resolve() == (args.snapshots / "audited-cells.json").resolve():
            raise ValueError("Output paths must not overwrite source, mapping or Books snapshots")
        if not args.saved:
            for name, report in reports.items():
                write_atomic_json(snapshot_paths[name], report)
        write_atomic_json(args.snapshots / "audited-cells.json", sheets)
        markdown = result.markdown
        for name, path in snapshot_paths.items():
            link = Path(os.path.relpath(path.resolve(), destination.resolve().parent)).as_posix()
            markdown = markdown.replace(f"]({name}.json)", f"](<{link}>)")
        with atomic_text_writer(destination) as handle:
            handle.write(markdown)
        print(destination.resolve())
        print(f"Books minus audited: net profit {result.net_profit_difference:,.2f}; assets {result.assets_difference:,.2f}")
        return 0
    except (ValueError, KeyError, IndexError, TypeError, OSError, InvalidOperation) as exc:
        parser.exit(1, f"Comparison failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
