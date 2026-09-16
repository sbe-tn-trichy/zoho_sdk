from unittest.mock import Mock

import pytest

from workflows.core.exceptions import ReconciliationError
from workflows.creator_beat_allocation import CreatorBeatAllocationService


def service():
    books = Mock()
    creator = Mock()
    contacts = [
        {"contact_id": "11", "contact_type": "customer", "status": "active", "cf_jurisdiction": "TRICHY"},
        {"contact_id": "12", "contact_type": "customer", "status": "active", "cf_jurisdiction": "MADURAI"},
        {"contact_id": "13", "contact_type": "customer", "status": "active"},
        {"contact_id": "14", "contact_type": "customer", "status": "inactive", "cf_jurisdiction": "TRICHY"},
    ]
    books.contacts.list_customers.return_value = contacts
    books.contacts.get.return_value = {"contact": contacts[0]}
    customers = [
        {"ID": "101", "Customer_Id": "11", "Name": "Alpha", "Beat.Beat_Name": ""},
        {"ID": "102", "Customer_Id": "12", "Name": "Beta", "Beat.Beat_Name": "Existing"},
        {"ID": "103", "Customer_Id": "13", "Name": "Gamma"},
        {"ID": "104", "Customer_Id": "14", "Name": "Inactive"},
    ]
    beats = [
        {"ID": "201", "Beat_Name": "Central", "Jurisdiction": {"Jurisdiction_Name": "TRICHY"}},
        {"ID": "202", "Beat_Name": "South", "Jurisdiction": {"Jurisdiction_Name": "MADURAI"}},
    ]
    creator.get_all_records.side_effect = lambda _app, report: beats if report == "All_Beats" else customers
    creator.update_records.return_value = {"code": 3000}
    return CreatorBeatAllocationService(books, creator, "app", "All_Customers1"), books, creator


def test_lists_only_active_unassigned_and_scopes_choices_to_jurisdiction():
    allocation, books, _ = service()
    rows = allocation.list_unallocated()
    books.contacts.list_customers.assert_called_once_with()
    assert [(row["name"], row["jurisdiction"], [beat["id"] for beat in row["beats"]]) for row in rows] == [
        ("Alpha", "TRICHY", ["201"]), ("Gamma", "", [])
    ]


def test_save_rechecks_jurisdiction_and_updates_one_record():
    allocation, _, creator = service()
    assert allocation.allocate("101", "11", "201")["beat"] == "Central"
    creator.update_records.assert_called_once_with(
        "app", "All_Customers1", payload={"data": {"Beat": "201"}}, record_id="101"
    )
    with pytest.raises(ReconciliationError, match="unavailable"):
        allocation.allocate("101", "11", "202")


def test_save_rejects_changed_or_existing_customer():
    allocation, books, creator = service()
    with pytest.raises(ReconciliationError, match="already has a beat"):
        allocation.allocate("102", "12", "202")
    with pytest.raises(ReconciliationError, match="no longer matches"):
        allocation.allocate("101", "12", "201")
    books.contacts.get.return_value = {"contact": {"contact_id": "11", "contact_type": "customer"}}
    with pytest.raises(ReconciliationError, match="no longer active"):
        allocation.allocate("101", "11", "201")
    creator.update_records.assert_not_called()


def test_save_rejects_inactive_customer():
    allocation, books, creator = service()
    books.contacts.get.return_value = {
        "contact": {"contact_id": "11", "contact_type": "customer", "status": "inactive", "cf_jurisdiction": "TRICHY"}
    }
    with pytest.raises(ReconciliationError, match="no longer active"):
        allocation.allocate("101", "11", "201")
    creator.update_records.assert_not_called()
