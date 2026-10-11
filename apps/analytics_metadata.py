"""Analyze cached Analytics metadata; use --sync to refresh it manually."""

import argparse
import json
from pathlib import Path

from workflows.analytics_catalog import AnalyticsCatalog
from workflows.core.auth import get_analytics_client
from workflows.core.checkpoint import write_atomic_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", default="264324000000002043")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--view-id", help="Limit analysis and include transitive workflow impact")
    parser.add_argument("--sync", action="store_true", help="Manually refresh metadata before analysis")
    args = parser.parse_args()
    catalog = AnalyticsCatalog(get_analytics_client() if args.sync else None, args.workspace_id, args.output)
    if args.sync:
        catalog.sync()
    result = catalog.analyze(args.view_id)
    write_atomic_json(catalog.output_dir / "analysis.json", result)
    lines = ["# Analytics metadata analysis", "",
             f"Last successful metadata sync (UTC): {result['last_successful_sync_at']}", "",
             "Source: cached SQLite. Refresh manually with `apps/analytics_metadata.py --sync`.", "",
             "| View | Type | Workflows |", "|---|---|---|"]
    lines.extend("| " + " | ".join(str(v[k]).replace("|", "\\|").replace("\n", " ")
                 for k in ("name", "view_type", "used_by_workflows")) + " |" for v in result["views"])
    (catalog.output_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"database": str(catalog.output_dir / "metadata.sqlite"),
                      "counts": result["sync"]["counts"],
                      "last_successful_sync_at": result["last_successful_sync_at"],
                      "source": result["source"]}, indent=2))


if __name__ == "__main__":
    main()
