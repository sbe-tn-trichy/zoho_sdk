"""Analytics baseline and Books modified-bill overlay."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from workflows.gstr2_verification import (
    GSTR2Verifier, convert_analytics_bills, refresh_bill_snapshot,
    unchanged_zero_tax_expenses,
)


NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
ROW = {"Bill ID": "1", "Vendor ID": "v1", "Bill Date": "02/04/2024",
       "Transaction Posting Date": "03/04/2024", "Bill Number": "B-1",
       "Bill Status": "Paid", "GSTIN": "33AAA", "Location ID": "loc1",
       "Total (BCY)": "INR 118.00", "Sub Total (BCY)": "100.00",
       "IGST Amount": "INR 18.00", "Last Modified Time": "2025-01-01 10:00:00"}
VENDOR = {"Vendor ID": "v1", "Vendor Name": "Supplier", "GSTIN": "33AAA"}


def test_analytics_mapping_preserves_posting_date_tax_and_vendor():
    bill = convert_analytics_bills([ROW], [VENDOR])[0]
    assert bill["txn_value_date"] == "2024-04-03"
    assert bill["vendor_name"] == "Supplier"
    assert bill["tax_total"] == 18
    assert bill["total"] == 118


def test_snapshot_overlays_recent_books_changes_and_reuses_cache(tmp_path):
    books = MagicMock()
    books.bills.list.return_value = {"bills": [{
        "bill_id": "1", "total": 120,
        "last_modified_time": (NOW - timedelta(hours=1)).isoformat(),
    }], "page_context": {"has_more_page": False}}
    loader = MagicMock(return_value=([ROW], [VENDOR], NOW - timedelta(hours=3)))
    path = tmp_path / "snapshot.json"
    first = refresh_bill_snapshot(books=books, snapshot_path=path,
                                  organization_id="org", workspace_id="ws",
                                  analytics_loader=loader, now=NOW)
    assert first[0]["total"] == 120
    assert books.bills.list.call_args.kwargs["params"]["last_modified_time"] == "2026-10-01T12:00:00+0000"
    books.bills.list.return_value = {"bills": [], "page_context": {"has_more_page": False}}
    second = refresh_bill_snapshot(books=books, snapshot_path=path,
                                   organization_id="org", workspace_id="ws",
                                   analytics_loader=loader, now=NOW + timedelta(hours=1))
    assert second[0]["total"] == 120
    assert loader.call_count == 1


def test_stale_analytics_baseline_fails_without_writing_snapshot(tmp_path):
    books = MagicMock()
    path = tmp_path / "snapshot.json"
    with pytest.raises(ValueError, match="older than 24 hours"):
        refresh_bill_snapshot(books=books, snapshot_path=path,
                              organization_id="org", workspace_id="ws",
                              analytics_loader=lambda: ([ROW], [VENDOR], NOW - timedelta(days=2)),
                              now=NOW)
    assert not path.exists()
    books.bills.list.assert_not_called()


def test_ignored_modified_filter_fails_without_writing_snapshot(tmp_path):
    books = MagicMock()
    books.bills.list.return_value = {"bills": [{
        "bill_id": "2", "last_modified_time": (NOW - timedelta(days=3)).isoformat(),
    }], "page_context": {"has_more_page": False}}
    path = tmp_path / "snapshot.json"
    with pytest.raises(ValueError, match="did not honor"):
        refresh_bill_snapshot(books=books, snapshot_path=path,
                              organization_id="org", workspace_id="ws",
                              analytics_loader=lambda: ([ROW], [VENDOR], NOW), now=NOW)
    assert not path.exists()


def test_unchanged_zero_tax_expense_skips_detail_read():
    modified = "2024-12-03T10:32:02+05:30"
    zero = unchanged_zero_tax_expenses([{
        "Expense ID": "e1", "Tax Value": "INR 0",
        "Last Modified Time": "2024-12-03 10:32:02",
    }])
    books = MagicMock()
    books.expenses.list_all.return_value = [{
        "expense_id": "e1", "date": "2024-12-02", "status": "paid",
        "reference_number": "E1", "last_modified_time": modified,
    }]
    verifier = GSTR2Verifier(books, bill_snapshot=[], zero_tax_expense_modified=zero)
    result = verifier.run({"data": {"gstin": "33AAA", "rtnprd": "122024",
                                    "docdata": {"b2b": [], "cdnr": []}}})
    assert result["reconciliation"]["summary"]["books_total_expenses_count"] == 0
    books.expenses.get.assert_not_called()
