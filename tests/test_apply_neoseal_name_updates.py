from __future__ import annotations

from unittest.mock import MagicMock
from workflows.neoseal_audit.naming_rules import (
    compute_item_update,
    standardize_item_name,
)
from apps.apply_neoseal_name_updates import run_plan_or_apply


def test_standardize_item_name_ball_valve_gs_plus():
    raw = '1" PVC Ball Valve GS PLUS'
    expected = '1" PVC Ball Valve GS Plus'
    assert standardize_item_name(raw) == expected


def test_standardize_item_name_solvents_and_ml_spacing():
    raw = "100 PVC Solution 100ml (Tin)"
    expected = "100 PVC Solvent Cement 100 ml (Tin)"
    assert standardize_item_name(raw) == expected


def test_standardize_item_name_si_mass_and_length():
    assert standardize_item_name("501 SBR Latex 1kg") == "501 SBR Latex 1 kg"
    assert standardize_item_name("503 Crack Filler Paste 500g") == "503 Crack Filler Paste 500 g"
    assert standardize_item_name("506 Terrace Coat 20L") == "506 Terrace Coat 20 L"
    assert standardize_item_name("PVC Insulation Tape 6mtr (BLUE)") == "PVC Insulation Tape 6 m (Blue)"


def test_compute_item_update_ptfe_tape_color_and_sku():
    item = {
        "item_id": "1094368000034939235",
        "name": "PTFE Tape Premium 12mm 5mtr Yellow",
        "sku": "5M-YELLOW-12MM",
        "stock": 1828.0,
    }
    update = compute_item_update(item)
    assert update is not None
    assert update["proposed_name"] == "PTFE Tape Premium 12 mm 5 m White"
    assert update["proposed_sku"] == "5M-WHITE-12MM"
    assert update["name_changed"] is True
    assert update["sku_changed"] is True


def test_compute_item_update_silicone_clear_sku():
    item = {
        "item_id": "1094368000037871675",
        "name": "701 GP Silicone Sealant 260 ml Clear",
        "sku": "701-260-C",
        "stock": 72.0,
    }
    update = compute_item_update(item)
    assert update is not None
    assert update["proposed_sku"] == "701-260-CLR"
    assert update["sku_changed"] is True


def test_compute_item_update_duplicate_detection():
    item_b = {
        "item_id": "1094368000056133772",
        "name": "701 GP Silicone Sealant 260 ml Black",
        "sku": "701-260-B",
        "stock": 0.0,
    }
    update_b = compute_item_update(item_b)
    assert update_b is not None
    assert update_b["is_duplicate"] is True
    assert "701-260-BLK" in update_b["duplicate_info"]["master_sku"]


from pathlib import Path

def test_run_plan_dry_run_never_mutates():
    mock_client = MagicMock()
    items = [
        {"item_id": "1", "name": '1" PVC Ball Valve GS PLUS', "sku": "1-PVC-GSP"},
        {"item_id": "2", "name": "100 PVC Solution 100ml (Tin)", "sku": "100-100-PVC-CLR-TIN"},
    ]
    test_out = Path("tests/.tmp_output")

    summary = run_plan_or_apply(
        items=items,
        apply=False,
        client=mock_client,
        output_dir=test_out,
    )

    assert summary["mode"] == "dry_run"
    assert summary["updates_required"] == 2
    mock_client.items.update.assert_not_called()
    mock_client.items.mark_as_inactive.assert_not_called()


def test_run_plan_apply_calls_update():
    mock_client = MagicMock()
    items = [
        {"item_id": "101", "name": '1" PVC Ball Valve GS PLUS', "sku": "1-PVC-GSP"},
        {"item_id": "102", "name": "701 GP Silicone Sealant 260 ml Black", "sku": "701-260-B"},
    ]
    test_out = Path("tests/.tmp_output")

    summary = run_plan_or_apply(
        items=items,
        apply=True,
        deactivate_duplicates=True,
        client=mock_client,
        output_dir=test_out,
    )

    assert summary["mode"] == "live_apply"
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 0

    # Item 101 name update
    mock_client.items.update.assert_any_call("101", {"name": '1" PVC Ball Valve GS Plus'})

    # Item 102 duplicate deactivation
    mock_client.items.mark_as_inactive.assert_called_once_with("102")
