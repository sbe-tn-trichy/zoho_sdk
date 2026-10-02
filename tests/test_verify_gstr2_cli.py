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


def test_build_monthly_report_filename():
    from datetime import datetime
    ts = datetime(2026, 9, 25, 14, 17)
    filename = verify_gstr2.build_monthly_report_filename("2025-04", run_timestamp=ts)
    assert filename == "Apr-2025_2509_1417.md"


def test_outputs_upsert_month_and_append_cumulative_history(tmp_path):
    from datetime import datetime
    root = tmp_path / "Output" / "GSTR2 Verification"
    fixed_ts = datetime(2025, 10, 20, 14, 15)

    monthly, cumulative = verify_gstr2.write_reconciliation_outputs(
        _result("2025-10", "first"), "October report", root, run_timestamp=fixed_ts,
    )
    assert monthly == root / "monthly" / "Oct-2025_2010_1415.md"
    assert monthly.read_text(encoding="utf-8") == "October report"
    assert cumulative

    verify_gstr2.write_reconciliation_outputs(
        _result("2025-10", "corrected"), "Corrected October report", root, run_timestamp=fixed_ts,
    )
    verify_gstr2.write_reconciliation_outputs(
        _result("2025-11", "second-month"), "November report", root, run_timestamp=fixed_ts,
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


def test_year_requires_every_return_before_connecting(tmp_path, monkeypatch, capsys):
    source = tmp_path / "returns"
    source.mkdir()
    (source / "apr.json").write_text(json.dumps({"rtnprd": "042025"}), encoding="utf-8")
    monkeypatch.setattr(verify_gstr2, "get_books_client",
                        lambda **kwargs: pytest.fail("should not connect"))
    assert verify_gstr2.main([str(source), "--year", "2025-26"]) == 1
    assert "missing FY returns" in capsys.readouterr().err


def test_year_runs_in_order_and_writes_adjusted_reports(tmp_path, monkeypatch, capsys):
    source = tmp_path / "returns"
    source.mkdir()
    for month in reversed(verify_gstr2.fiscal_months(2025)):
        (source / f"{month}.json").write_text(json.dumps({
            "rtnprd": month[5:] + month[:4], "gstin": "33AAA",
        }), encoding="utf-8")
    seen = []

    class FakeVerifier:
        def __init__(self, books, config, bill_snapshot, expense_snapshot, credit_snapshot):
            pass

        def run(self, gstr2_source, month):
            data = json.loads(gstr2_source.read_text(encoding="utf-8"))
            period = data["rtnprd"]
            target = period[2:] + "-" + period[:2]
            seen.append(target)
            return {"metadata": {"target_month": target, "recipient_gstin": "33AAA"},
                    "reconciliation": {"summary": {}, "missing_in_books": [],
                                       "missing_in_gstr2_bills": [],
                                       "missing_in_gstr2_expenses": [],
                                       "missing_in_gstr2_credits": [],
                                       "matched_documents": [], "aggregate_matches": [],
                                       "vendor_summaries": []}}

    monkeypatch.setattr(verify_gstr2, "get_books_client", lambda **kwargs: MagicMock())
    monkeypatch.setattr(verify_gstr2, "GSTR2Verifier", FakeVerifier)
    monkeypatch.setattr(verify_gstr2, "refresh_bill_snapshot", lambda **kwargs: [])
    monkeypatch.setattr(verify_gstr2, "refresh_purchase_snapshot", lambda **kwargs: [])
    monkeypatch.setattr(verify_gstr2, "render_markdown_report",
                        lambda result: result["metadata"]["target_month"])
    root = tmp_path / "reports"
    assert verify_gstr2.main([str(source), "--year", "2025-26",
                              "--output-root", str(root)]) == 0
    assert seen == list(verify_gstr2.fiscal_months(2025))
    assert (root / "yearly" / "FY-2025-26.md").exists()
    output = capsys.readouterr().out
    assert "Month 12/12 completed" in output
    assert "Progress: 12/12 months completed; 0 HTTP attempts" in output


def test_run_metrics_logs_every_attempt_without_record_ids(monkeypatch, capsys):
    ticks = iter([100.0, 101.0, 104.0])
    monkeypatch.setattr(verify_gstr2.time, "monotonic", lambda: next(ticks))
    metrics = verify_gstr2.RunMetrics()
    metrics.total_months = 12
    metrics.on_start("books", "GET", "expenses/123")
    metrics.on_attempt("books", "GET", "expenses/123", 2.5, 200)
    assert metrics.summary(12) == (
        "Progress: 0/12 months completed; 1 HTTP attempts; 4.0s elapsed. "
        "Requests by resource: books/expenses detail: 1 (2.5s HTTP)"
    )
    output = capsys.readouterr().out
    assert "HTTP start: GET books/expenses detail" in output
    assert "HTTP done: GET books/expenses detail; status=200; duration=2.5s" in output
    assert "123" not in output
