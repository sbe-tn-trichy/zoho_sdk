import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest



from workflows.core.exceptions import ReconciliationError
from workflows.creator_customer_delete_sync import (
    CreatorCustomerDeleteSyncConfig,
    CreatorCustomerDeleteSyncer,
    sync_creator_customer_deletions,
)


@pytest.fixture
def mock_books_client():
    client = MagicMock()
    client.contacts.list_all.return_value = [
        {"contact_id": "10001", "contact_name": "Acme Corp", "contact_type": "customer"},
        {"contact_id": "10002", "contact_name": "Beta LLC", "contact_type": "customer"},
    ]
    return client


@pytest.fixture
def mock_creator_client():
    client = MagicMock()
    client.get_all_records.return_value = [
        {"ID": "30001", "Customer_Id": "10001", "Customer_Name": "Acme Corp"},
        {"ID": "30002", "Customer_Id": "10002", "Customer_Name": "Beta LLC"},
        {"ID": "30003", "Customer_Id": "10003", "Customer_Name": "Orphaned Inc"},
    ]
    client.delete_records.return_value = {"code": 3000, "message": "Record deleted successfully"}
    client.update_records.return_value = {"code": 3000, "message": "Record updated successfully"}
    return client



def test_dry_run_mode(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        dry_run=True,
        max_deletion_percentage=50.0,
        output_dir=tmp_path,
    )
    
    syncer = CreatorCustomerDeleteSyncer(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    summary = syncer.execute_sync()
    
    assert summary["dry_run"] is True
    assert summary["scanned_books_customer_keys_count"] == 2
    assert summary["scanned_creator_records_count"] == 3
    assert summary["matched_records_count"] == 2
    assert summary["candidate_delete_count"] == 1
    assert summary["records"][0]["creator_record_id"] == "30003"
    assert summary["records"][0]["action"] == "WOULD_DELETE"
    
    # Creator delete_records must NOT be called in dry-run mode
    mock_creator_client.delete_records.assert_not_called()


def test_execute_live_deletions(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        dry_run=False,
        max_deletion_percentage=50.0,
        output_dir=tmp_path,
    )
    
    summary = sync_creator_customer_deletions(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    assert summary["dry_run"] is False
    assert summary["deleted_count"] == 1
    assert summary["records"][0]["action"] == "HARD_DELETED"
    
    mock_creator_client.delete_records.assert_called_once_with(
        "customer_app", "All_Customers", record_id="30003"
    )


def test_soft_delete_mode(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        dry_run=False,
        soft_delete_field="Is_Deleted",
        soft_delete_value=True,
        max_deletion_percentage=50.0,
        output_dir=tmp_path,
    )
    
    syncer = CreatorCustomerDeleteSyncer(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    summary = syncer.execute_sync()
    
    assert summary["records"][0]["action"] == "SOFT_DELETED"
    mock_creator_client.delete_records.assert_not_called()
    mock_creator_client.update_records.assert_called_once_with(
        "customer_app",
        "All_Customers",
        payload={"Is_Deleted": True},
        record_id="30003",
    )


def test_safety_limit_max_deletions(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        max_deletion_limit=0,  # 0 limit will trigger exception if candidate count > 0
        max_deletion_percentage=50.0,
        output_dir=tmp_path,
    )
    
    syncer = CreatorCustomerDeleteSyncer(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    with pytest.raises(ReconciliationError, match="Safety Threshold Exceeded: Candidate deletion count"):
        syncer.execute_sync()


def test_safety_limit_percentage(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        max_deletion_percentage=10.0,  # 1 candidate out of 3 = 33.3% > 10.0%
        output_dir=tmp_path,
    )
    
    syncer = CreatorCustomerDeleteSyncer(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    with pytest.raises(ReconciliationError, match="Safety Threshold Exceeded: Candidate deletion percentage"):
        syncer.execute_sync()


def test_report_json_file_creation(mock_books_client, mock_creator_client, tmp_path):
    config = CreatorCustomerDeleteSyncConfig(
        app_link_name="customer_app",
        report_link_name="All_Customers",
        max_deletion_percentage=50.0,
        output_dir=tmp_path,
    )

    
    syncer = CreatorCustomerDeleteSyncer(
        books_client=mock_books_client,
        creator_client=mock_creator_client,
        config=config,
    )
    
    summary = syncer.execute_sync()
    report_file_path = tmp_path / Path(summary["report_file"]).name
    
    assert report_file_path.exists()
    with open(report_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["scanned_creator_records_count"] == 3
