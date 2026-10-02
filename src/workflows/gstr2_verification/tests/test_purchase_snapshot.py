"""Analytics expense and vendor-credit baselines with bounded Books changes."""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import pytest

from workflows.gstr2_verification import (
    GSTR2Verifier, convert_analytics_credits, convert_analytics_expenses,
    refresh_purchase_snapshot,
)


NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def test_analytics_conversions_preserve_matching_tax_and_location():
    expenses = convert_analytics_expenses([{
        "Expense ID": "e1", "Expense Date": "01/05/2024",
        "Last Modified Time": "2024-05-02 10:00:00", "Tax Value": "INR 18.00",
        "Total (BCY)": "INR 118.00", "Sub Total (BCY)": "INR 100.00",
        "GSTIN": "33ABC", "Location ID": "l1", "Reference Number": "INV-1",
    }])
    assert expenses[0]["tax_amount"] == 18
    assert expenses[0]["date"] == "2024-05-01"
    assert expenses[0]["location_id"] == "l1"
    assert expenses[0]["reference_number"] == "INV-1"
    credits = convert_analytics_credits([{
        "Vendor Credit ID": "c1", "Vendor Credit Date": "02/05/2024",
        "Last Modified Time": "2024-05-03 10:00:00", "GST Present": "INR 9.00",
        "Total (BCY)": "INR 59.00", "Location ID": "l1",
        "Vendor Name": "Example Vendor",
    }])
    assert credits[0]["tax_total"] == 9
    assert credits[0]["date"] == "2024-05-02"
    assert credits[0]["vendor_name"] == "Example Vendor"


def test_snapshot_overlays_recent_changes_and_reuses_cache(tmp_path):
    books = MagicMock()
    books.expenses.list.return_value = {"expenses": [{
        "expense_id": "e1", "date": "2024-06-01", "tax_amount": 0,
        "last_modified_time": "2026-10-02T11:00:00+0000",
    }], "page_context": {"has_more_page": False}}
    loader = MagicMock(return_value=([{
        "Expense ID": "e1", "Expense Date": "01/05/2024",
        "Last Modified Time": "2024-05-02 10:00:00", "Tax Value": "INR 18.00",
    }], NOW))
    path = tmp_path / "expenses.json"
    params = dict(books=books, resource="expenses", snapshot_path=path,
                  organization_id="org", workspace_id="workspace",
                  analytics_loader=loader, now=NOW)
    assert refresh_purchase_snapshot(**params)[0]["date"] == "2024-06-01"
    assert refresh_purchase_snapshot(**params)[0]["date"] == "2024-06-01"
    loader.assert_called_once()
    assert books.expenses.list.call_count == 2


def test_snapshot_rejects_ignored_modified_filter_without_replacing_cache(tmp_path):
    books = MagicMock()
    books.vendor_credits.list.return_value = {"vendor_credits": [{
        "vendor_credit_id": "c1", "last_modified_time": "2024-05-03T10:00:00+0000",
    }]}
    path = tmp_path / "credits.json"
    previous = json.dumps({"schema_version": 1, "resource": "vendor_credits",
                           "organization_id": "org", "workspace_id": "workspace",
                           "checked_at": NOW.isoformat(), "analytics_at": NOW.isoformat(),
                           "rows": []})
    path.write_text(previous, encoding="utf-8")
    with pytest.raises(ValueError, match="did not honor"):
        refresh_purchase_snapshot(
            books=books, resource="vendor_credits", snapshot_path=path,
            organization_id="org", workspace_id="workspace", now=NOW,
            analytics_loader=lambda: ([{
                "Vendor Credit ID": "c1", "Vendor Credit Date": "02/05/2024",
                "Last Modified Time": "2024-05-03 10:00:00", "GST Present": "INR 9.00",
            }], NOW),
        )
    assert path.read_text(encoding="utf-8") == previous


def test_snapshot_accepts_vendorcredits_response_key(tmp_path):
    books = MagicMock()
    books.vendor_credits.list.return_value = {"vendorcredits": [],
                                               "page_context": {"has_more_page": False}}
    rows = refresh_purchase_snapshot(
        books=books, resource="vendor_credits", snapshot_path=tmp_path / "credits.json",
        organization_id="org", workspace_id="workspace", now=NOW,
        analytics_loader=lambda: ([{
            "Vendor Credit ID": "c1", "Vendor Credit Date": "02/05/2024",
            "Last Modified Time": "2024-05-03 10:00:00", "GST Present": "INR 9.00",
        }], NOW),
    )
    assert rows[0]["vendor_credit_id"] == "c1"


def test_verifier_filters_snapshots_by_month_without_list_calls():
    from datetime import date

    books = MagicMock()
    verifier = GSTR2Verifier(books, expense_snapshot=[{
        "expense_id": "e1", "date": "2024-05-01", "tax_amount": 18,
        "total": 118, "location_id": "l1", "gst_no": "33ABC",
    }, {"expense_id": "e2", "date": "2024-06-01", "tax_amount": 18,
        "total": 118, "location_id": "l1", "gst_no": "33ABC"}],
        credit_snapshot=[{"vendor_credit_id": "c1", "date": "2024-05-02",
                          "total": 59, "tax_total": 9, "location_id": "l1",
                          "gst_no": "33ABC"}])
    scope = {"l1": {"gstin": "33BUYER"}}
    expenses = verifier._fetch_books_expenses(date(2024, 5, 1), date(2024, 5, 31),
                                               [], scope, "33BUYER")
    credits = verifier._fetch_books_vendor_credits(date(2024, 5, 1),
                                                    date(2024, 5, 31), [], scope, "33BUYER")
    assert [row["expense_id"] for row in expenses] == ["e1"]
    assert [row["credit_id"] for row in credits] == ["c1"]
    books.expenses.list_all.assert_not_called()
    books.vendor_credits.list_all.assert_not_called()
