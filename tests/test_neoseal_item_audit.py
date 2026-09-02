"""Tests for the Neoseal inventory item audit workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

from apps import audit_neoseal_items
from workflows.neoseal_audit import (
    NeosealItemAuditor,
    audit_neoseal_items as run_audit,
    render_markdown_report,
)


def _make_sample_items() -> list[dict]:
    return [
        # Ball valves: one GS PLUS (casing issue), one valid
        {
            "item_id": "bv-1",
            "name": "1 1/4\" PVC Ball Valve GS PLUS",
            "sku": "1.25-PVC-GSP",
            "status": "active",
            "group_name": "PVC Ball Valve",
            "stock_on_hand": 50.0,
        },
        {
            "item_id": "bv-2",
            "name": "1\" UPVC Ball Valve GS",
            "sku": "1-UPVC-GS",
            "status": "active",
            "group_name": "UPVC Ball Valve",
            "stock_on_hand": 100.0,
        },
        # Solvents: Packaging twins (Tin vs PVC Can)
        {
            "item_id": "solv-1",
            "name": "200 UPVC Solution 100ml Blue (PVC Can)",
            "sku": "200-100-UPVC-BLU-CAN",
            "status": "active",
            "group_name": "UPVC Solvent",
            "stock_on_hand": -9.0,
        },
        {
            "item_id": "solv-2",
            "name": "200 UPVC Solution 100ml Blue (Tin)",
            "sku": "200-100-UPVC-BLU-TIN",
            "status": "active",
            "group_name": "UPVC Solvent",
            "stock_on_hand": 361.0,
        },
        # Inverted solvent SKU in catch-all group
        {
            "item_id": "solv-3",
            "name": "PVC-UPVC Solution 20ml (Tube)",
            "sku": "20-PVC-UPVC-CLR-TUBE",
            "status": "active",
            "group_name": "Solvent Others",
            "stock_on_hand": 82.0,
        },
        # Tapes: legacy inactive duplicate & all-caps insulation tape
        {
            "item_id": "tape-1",
            "name": "PTFE Tape Premium 12mm 10mtr",
            "sku": "10mtr tape",
            "status": "inactive",
            "group_name": "",
            "stock_on_hand": 0.0,
        },
        {
            "item_id": "tape-2",
            "name": "PTFE Tape Premium 12mm 10mtr Yellow",
            "sku": "10M-YELLOW-12MM",
            "status": "active",
            "group_name": "PTFE Tape",
            "stock_on_hand": 1654.0,
        },
        {
            "item_id": "tape-3",
            "name": "PVC Insulation Tape 6mtr (BLUE)",
            "sku": "6M-INSULATION-BLUE",
            "status": "active",
            "group_name": "Insulation Tape",
            "stock_on_hand": 470.0,
        },
        # Chemical: Missing unit in SKU & ND40 missing brand hyphen
        {
            "item_id": "chem-1",
            "name": "501 SBR Latex 1kg",
            "sku": "501-1",
            "status": "active",
            "group_name": "SBR Latex",
            "stock_on_hand": 19.0,
        },
        {
            "item_id": "chem-2",
            "name": "ND-40 Multi Purpose Lube Spray 50ml",
            "sku": "ND40-50",
            "status": "active",
            "group_name": "ND-40 Lubricant",
            "stock_on_hand": 60.0,
        },
        # Accounting helper without group
        {
            "item_id": "cn-1",
            "name": "Solvent Rate Difference",
            "sku": "Neoseal CN",
            "status": "active",
            "group_name": "",
            "stock_on_hand": 0.0,
        },
    ]


def test_detects_duplicates_and_container_twins() -> None:
    items = _make_sample_items()
    auditor = NeosealItemAuditor(items)
    dupes = auditor.find_duplicates()

    match_types = {d["match_type"] for d in dupes}
    assert "packaging_twin" in match_types
    assert "legacy_duplicate" in match_types

    # Verify packaging twin matches Tin vs PVC Can
    twin = next(d for d in dupes if d["match_type"] == "packaging_twin")
    assert "200 UPVC Solution 100ml Blue" in twin["item_a"]["name"]
    assert "200 UPVC Solution 100ml Blue" in twin["item_b"]["name"]

    # Verify legacy duplicate matches PTFE Tape
    legacy = next(d for d in dupes if d["match_type"] == "legacy_duplicate")
    assert "PTFE Tape Premium 12mm 10mtr" in legacy["item_a"]["name"]


def test_detects_naming_anomalies() -> None:
    items = _make_sample_items()
    auditor = NeosealItemAuditor(items)
    naming_issues = auditor.check_naming_nomenclature()

    issue_types = {issue["issue_type"] for issue in naming_issues}
    assert "casing_convention" in issue_types

    # GS PLUS should be flagged
    gs_plus = next(i for i in naming_issues if "GS PLUS" in i["name"])
    assert gs_plus["recommendation"] == "1 1/4\" PVC Ball Valve GS Plus"

    # All-caps (BLUE) should be flagged
    blue_tape = next(i for i in naming_issues if "(BLUE)" in i["name"])
    assert "(Blue)" in blue_tape["recommendation"]


def test_detects_sku_nomenclature_anomalies() -> None:
    items = _make_sample_items()
    auditor = NeosealItemAuditor(items)
    sku_issues = auditor.check_sku_nomenclature()

    issue_types = {issue["issue_type"] for issue in sku_issues}
    assert "inverted_sku_structure" in issue_types
    assert "missing_unit_suffix" in issue_types
    assert "legacy_sku_format" in issue_types
    assert "brand_hyphenation" in issue_types

    # Inverted solvent
    inverted = next(i for i in sku_issues if i["issue_type"] == "inverted_sku_structure")
    assert inverted["recommendation"] == "UPVC-20-CLR-TUBE"

    # SBR Latex unit suffix
    chem = next(i for i in sku_issues if i["item_id"] == "chem-1")
    assert chem["recommendation"] == "501-1KG"

    # ND-40 hyphen
    lube = next(i for i in sku_issues if i["item_id"] == "chem-2")
    assert lube["recommendation"] == "ND-40-50"


def test_detects_missing_and_catchall_groups() -> None:
    items = _make_sample_items()
    auditor = NeosealItemAuditor(items)
    group_issues = auditor.check_group_categorization()

    issue_types = {issue["issue_type"] for issue in group_issues}
    assert "missing_group" in issue_types
    assert "catchall_group" in issue_types

    # Accounting helper recommended for Neoseal Adjustment
    cn_issue = next(i for i in group_issues if i["sku"] == "Neoseal CN")
    assert cn_issue["recommended_group"] == "Neoseal Adjustment"

    # Solvent Others recommended for UPVC Solvent
    catchall = next(i for i in group_issues if i["current_group"] == "Solvent Others")
    assert catchall["recommended_group"] == "UPVC Solvent"


def test_render_markdown_report() -> None:
    items = _make_sample_items()
    result = run_audit(items)
    report = render_markdown_report(result, {"source": "Test Suite", "checked_at": "2026-09-02"})

    assert "# Neoseal Inventory Item Audit & Nomenclature Report" in report
    assert "## Executive Summary" in report
    assert "## 1. Duplicates & Twin Variants" in report
    assert "## Action Checklist" in report
    assert "GS Plus" in report
    assert "UPVC-20-CLR-TUBE" in report


def test_cli_main_with_csv(tmp_path: Path) -> None:
    csv_file = tmp_path / "test_items.csv"
    items = _make_sample_items()
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(items[0].keys()))
        writer.writeheader()
        writer.writerows(items)

    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"

    rc = audit_neoseal_items.main([
        "--input-csv", str(csv_file),
        "--output", str(out_md),
        "--json-output", str(out_json),
    ])

    assert rc == 0
    assert out_md.exists()
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["result"]["total_audited"] == len(items)


def test_cli_main_with_mock_books(monkeypatch, tmp_path: Path) -> None:
    books = MagicMock()
    books.items.list_by_purchase_account.return_value = _make_sample_items()
    monkeypatch.setattr(audit_neoseal_items, "get_books_client", lambda: books)

    out_md = tmp_path / "report.md"
    rc = audit_neoseal_items.main([
        "--purchase-account-id", "mock-account-id",
        "--output", str(out_md),
    ])

    assert rc == 0
    assert out_md.exists()
    books.items.list_by_purchase_account.assert_called_once_with(
        "mock-account-id",
        status="all",
    )
