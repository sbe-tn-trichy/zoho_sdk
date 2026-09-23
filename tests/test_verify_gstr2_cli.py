"""Safety checks for the GSTR-2B report runner."""

import csv
import json

import pytest
from unittest.mock import MagicMock

from apps import verify_gstr2


def _result(month, mismatch_marker):
    return {
        "metadata": {"target_month": month},
        "reconciliation": {
            "summary": {"value_mismatch_count": 1},
            "value_mismatches": [{"marker": mismatch_marker}],
        },
    }


def test_incomplete_fetch_does_not_overwrite_report(tmp_path, monkeypatch, capsys):
    source = tmp_path / "return.json"
    source.write_text("{}", encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("previous valid report", encoding="utf-8")
    monkeypatch.setattr(verify_gstr2, "get_books_client", lambda **kwargs: MagicMock())
    monkeypatch.setattr(verify_gstr2, "verify_gstr2", lambda **kwargs: {
        "fetch_errors": [{"source": "bills", "error": "not authorized"}],
    })

    exit_code = verify_gstr2.main([str(source), "--output", str(report)])

    assert exit_code == 1
    assert report.read_text(encoding="utf-8") == "previous valid report"
    assert "Reconciliation incomplete" in capsys.readouterr().err


def test_unresolved_location_does_not_overwrite_report(tmp_path, monkeypatch):
    source = tmp_path / "return.json"
    source.write_text("{}", encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("previous valid report", encoding="utf-8")
    monkeypatch.setattr(verify_gstr2, "get_books_client", lambda **kwargs: MagicMock())
    monkeypatch.setattr(verify_gstr2, "verify_gstr2", lambda **kwargs: {
        "fetch_errors": [{"source": "locations", "error": "Unknown location"}],
    })

    assert verify_gstr2.main([str(source), "--output", str(report)]) == 1
    assert report.read_text(encoding="utf-8") == "previous valid report"


def test_outputs_upsert_month_and_append_cumulative_history(tmp_path):
    root = tmp_path / "Output" / "GSTR2 Verification"

    monthly, cumulative = verify_gstr2.write_reconciliation_outputs(
        _result("2025-10", "first"), "October report", root,
    )
    assert monthly == root / "monthly" / "2025-10.md"
    assert monthly.read_text(encoding="utf-8") == "October report"
    assert cumulative

    verify_gstr2.write_reconciliation_outputs(
        _result("2025-10", "corrected"), "Corrected October report", root,
    )
    verify_gstr2.write_reconciliation_outputs(
        _result("2025-11", "second-month"), "November report", root,
    )

    assert monthly.read_text(encoding="utf-8") == "Corrected October report"
    with (root / "cumulative" / "Value Mismatches.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {"month": "2025-10", "marker": "corrected"},
        {"month": "2025-11", "marker": "second-month"},
    ]
    assert not list((root / "cumulative").glob("*.json"))


def test_corrupt_cumulative_file_is_not_silently_overwritten(tmp_path):
    root = tmp_path / "Output" / "GSTR2 Verification"
    path = root / "cumulative" / "Value Mismatches.csv"
    path.parent.mkdir(parents=True)
    path.write_text("not csv\nvalue", encoding="utf-8")

    with pytest.raises(ValueError, match="Unable to update cumulative output"):
        verify_gstr2.write_reconciliation_outputs(
            _result("2025-10", "first"), "October report", root,
        )


def test_existing_json_history_is_migrated_to_csv(tmp_path):
    root = tmp_path / "Output" / "GSTR2 Verification"
    old = root / "cumulative" / "Value Mismatches.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"2025-09": [{"marker": "earlier"}]}), encoding="utf-8")

    verify_gstr2.write_reconciliation_outputs(
        _result("2025-10", "new"), "October report", root,
    )

    with old.with_suffix(".csv").open(newline="") as handle:
        assert list(csv.DictReader(handle)) == [
            {"month": "2025-09", "marker": "earlier"},
            {"month": "2025-10", "marker": "new"},
        ]
    assert not old.exists()
