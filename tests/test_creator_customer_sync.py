from unittest.mock import MagicMock

import pytest

from workflows import CreatorCustomerSyncConfig, sync_creator_customers
from workflows.core.exceptions import ReconciliationError


def clients():
    books, creator = MagicMock(), MagicMock()
    books.contacts.list_all.return_value = [
        {"contact_id": "1", "contact_name": "Changed", "contact_type": "customer"},
        {"contact_id": "2", "contact_name": "New", "contact_type": "customer"},
        {"contact_id": "3", "contact_name": "Same", "contact_type": "customer", "status": "inactive"},
        {"contact_id": "vendor", "contact_type": "vendor"},
    ]
    creator.get_all_records.return_value = [
        {"ID": "a", "Customer_Id": "1", "Customer_Name": "Old"},
        {"ID": "c", "customer_id": 3, "Customer_Name": "Same"},
        {"ID": "d", "Customer_Id": "4"},
    ]
    return books, creator


def config(tmp_path, **kwargs):
    return CreatorCustomerSyncConfig("app", "report", form_link_name="form",
                                     output_dir=tmp_path, max_deletion_percentage=100, **kwargs)


@pytest.mark.parametrize("dry_run", [True, False])
def test_full_reconciliation(tmp_path, dry_run):
    books, creator = clients()
    result = sync_creator_customers(books, creator, config(tmp_path, dry_run=dry_run))
    assert result["unchanged_count"] == 1
    for action in ("create", "update", "delete"):
        assert result[f"candidate_{action}_count"] == 1
    assert result["created_count"] == (0 if dry_run else 1)
    if dry_run:
        creator.add_records.assert_not_called()
        creator.update_records.assert_not_called()
        creator.delete_records.assert_not_called()
    else:
        creator.add_records.assert_called_once_with("app", "form", payload={"data": [
            {"Customer_Id": "2", "Customer_Name": "New"}]})
        creator.update_records.assert_called_once_with("app", "report",
            payload={"data": {"Customer_Name": "Changed"}}, record_id="a")
        creator.delete_records.assert_called_once_with("app", "report", record_id="d")


@pytest.mark.parametrize("problem", ["duplicate", "missing_id", "threshold", "missing_form", "fetch_error"])
def test_preflight_failures_do_not_mutate(tmp_path, problem):
    books, creator = clients()
    cfg = config(tmp_path, dry_run=False)
    if problem == "duplicate":
        creator.get_all_records.return_value.append(creator.get_all_records.return_value[0])
    elif problem == "missing_id":
        del creator.get_all_records.return_value[0]["ID"]
    elif problem == "threshold":
        cfg.max_deletion_limit = 0
    elif problem == "missing_form":
        cfg.form_link_name = None
    else:
        books.contacts.list_all.side_effect = ReconciliationError("fetch failed")
    with pytest.raises(ReconciliationError):
        sync_creator_customers(books, creator, cfg)
    creator.add_records.assert_not_called()
    creator.update_records.assert_not_called()
    creator.delete_records.assert_not_called()


def test_detail_mapping_and_blank_clearing(tmp_path):
    books, creator = clients()
    books.contacts.list_all.return_value = books.contacts.list_all.return_value[:1]
    creator.get_all_records.return_value = creator.get_all_records.return_value[:1]
    creator.get_all_records.return_value[0]["Email"] = "old@example.com"
    books.contacts.get.return_value = {"contact": {"contact_id": "1", "email": ""}}
    cfg = config(tmp_path, dry_run=False, field_mapping={"Email": "email"})
    sync_creator_customers(books, creator, cfg)
    books.contacts.get.assert_called_once_with("1")
    creator.update_records.assert_called_once_with("app", "report",
        payload={"data": {"Email": ""}}, record_id="a")


def test_mutation_error_stops_before_deletion(tmp_path):
    books, creator = clients()
    creator.update_records.side_effect = RuntimeError("API failure")
    with pytest.raises(RuntimeError, match="API failure"):
        sync_creator_customers(books, creator, config(tmp_path, dry_run=False))
    creator.delete_records.assert_not_called()


def test_empty_creator_creates_all_customers(tmp_path):
    books, creator = clients()
    creator.get_all_records.return_value = []
    result = sync_creator_customers(books, creator, config(tmp_path))
    assert result["candidate_create_count"] == 3
    assert result["candidate_delete_count"] == 0


def test_active_branch_scope_preserves_excluded_creator_customers(tmp_path):
    books, creator = clients()
    rows = books.contacts.list_all.return_value
    rows[0].update(status="active", cf_b_name="Electricals")
    rows[1].update(status="active", cf_b_name="Opticals")
    rows[2].update(cf_b_name="Electricals")
    cfg = config(tmp_path, books_status_filter="active", books_branch_name="Electricals")
    result = sync_creator_customers(books, creator, cfg)
    assert result["scanned_books_customer_keys_count"] == 1
    assert result["candidate_create_count"] == 0
    assert result["candidate_update_count"] == 1
    assert result["candidate_delete_count"] == 1
    assert result["excluded_creator_records_count"] == 1
    assert [r["customer_key"] for r in result["records"] if r["operation"] == "DELETE"] == ["4"]


def test_branch_custom_field_and_no_match(tmp_path):
    books, creator = clients()
    books.contacts.list_all.return_value = [{"contact_id": "1", "contact_type": "customer",
        "contact_name": "A", "status": "active", "custom_fields": [
            {"api_name": "cf_b_name", "value": "Electricals"}]}]
    cfg = config(tmp_path, books_status_filter="active", books_branch_name="electricals")
    result = sync_creator_customers(books, creator, cfg)
    assert result["scanned_books_customer_keys_count"] == 1
    cfg.books_branch_name = "Other"
    result = sync_creator_customers(books, creator, cfg)
    assert result["candidate_create_count"] == 0
    assert result["candidate_update_count"] == 0
    assert result["excluded_creator_records_count"] == 1


def test_invalid_status_fails_before_fetch(tmp_path):
    books, creator = clients()
    with pytest.raises(ReconciliationError, match="books_status_filter"):
        sync_creator_customers(books, creator, config(tmp_path, books_status_filter="typo"))
    books.contacts.list_all.assert_not_called()
