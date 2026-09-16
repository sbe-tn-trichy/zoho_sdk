from unittest.mock import Mock

import pytest

from workflows.core.exceptions import ReconciliationError
from workflows.creator_beat_sync import sync_creator_beats


def clients():
    books, creator = Mock(), Mock()
    books.custom_fields.list_for_entity.return_value = [{"api_name": "cf_beat", "index": 10}]
    creator.get_all_records.return_value = [
        {"ID": "101", "Customer_Id": "11", "Beat.Beat_Name": "Central"},
        {"ID": "102", "Customer_Id": "12", "Beat.Beat_Name": ""},
        {"ID": "103", "Customer_Id": "13", "Beat.Beat_Name": "South"},
    ]
    books.contacts.list_customers.return_value = [
        {"contact_id": contact_id, "contact_type": "customer",
         "status": "active", "contact_name": contact_id,
         "custom_field_hash": {"cf_beat": "South" if contact_id == "13" else "Old"}}
        for contact_id in ("11", "13")
    ]
    books.contacts.update.return_value = {"code": 0}
    return books, creator


def test_preview_and_apply_only_changed_assigned_beats():
    books, creator = clients()
    preview = sync_creator_beats(books, creator, "app", "All_Customers1")
    assert (preview["scanned"], preview["skipped_unassigned"], preview["unchanged"], preview["updated"]) == (3, 1, 1, 0)
    assert [change["books_id"] for change in preview["changes"]] == ["11"]
    books.contacts.update.assert_not_called()
    applied = sync_creator_beats(books, creator, "app", "All_Customers1", apply=True)
    assert applied["updated"] == 1
    books.contacts.update.assert_called_once_with("11", {"custom_fields": [{"index": 10, "value": "Central"}]})


def test_rejects_duplicate_before_any_write():
    books, creator = clients()
    creator.get_all_records.return_value.append({"ID": "104", "Customer_Id": "11", "Beat.Beat_Name": "Other"})
    with pytest.raises(ReconciliationError, match="Duplicate"):
        sync_creator_beats(books, creator, "app", "report", apply=True)
    books.contacts.update.assert_not_called()


def test_rejects_missing_field_and_failed_write():
    books, creator = clients()
    books.custom_fields.list_for_entity.return_value = []
    with pytest.raises(ReconciliationError, match="missing"):
        sync_creator_beats(books, creator, "app", "report", apply=True)
    books.custom_fields.list_for_entity.return_value = [{"api_name": "cf_beat", "index": 10}]
    books.contacts.update.return_value = {"code": 1}
    with pytest.raises(ReconciliationError, match="did not confirm"):
        sync_creator_beats(books, creator, "app", "report", apply=True)


def test_skips_assigned_creator_customer_absent_from_active_books_list():
    books, creator = clients()
    books.contacts.list_customers.return_value = []
    result = sync_creator_beats(books, creator, "app", "report", apply=True)
    assert result["skipped_inactive"] == 2
    assert result["changes"] == []
    books.contacts.update.assert_not_called()
