from unittest.mock import Mock
import pytest

from workflows import sync_customer_numbers, ReconciliationError


@pytest.fixture
def clients():
    books, creator = Mock(), Mock()
    books.contacts.get.return_value = {"code": 0, "contact": {"contact_id": "123", "contact_type": "customer", "contact_name": "Example", "contact_number": "CX123"}}
    creator.get_all_records.return_value = [{"ID": "456", "Customer_Id": "123", "Customer_no": ""}]
    creator.update_records.return_value = {"code": 3000, "result": [{"code": 3000}]}
    creator.get_records.return_value = {"code": 3000, "data": [{"ID": "456", "Customer_Id": "123", "Customer_no": "CX123"}]}
    return books, creator


def test_preview(clients):
    books, creator = clients
    result = sync_customer_numbers(books, creator, ["123"])
    assert result.dry_run and result.updated == 0
    assert result.changes[0].books_number == "CX123"
    creator.update_records.assert_not_called()
    books.contacts.create.assert_not_called()
    creator.delete_records.assert_not_called()


def test_apply_and_verify(clients):
    books, creator = clients
    result = sync_customer_numbers(books, creator, ["123"], dry_run=False)
    assert result.updated == 1
    creator.update_records.assert_called_once_with("order-management-new", "All_Customers1", record_id="456", payload={"data": {"Customer_no": "CX123"}, "skip_workflow": ["all"]})
    creator.get_records.assert_called_once()


def test_unchanged(clients):
    books, creator = clients
    creator.get_all_records.return_value[0]["Customer_no"] = "CX123"
    result = sync_customer_numbers(books, creator, ["123"], dry_run=False)
    assert result.unchanged == 1 and not result.changes
    creator.update_records.assert_not_called()


@pytest.mark.parametrize("ids", [[], ["123", "123"], ["abc"], [""]])
def test_invalid_ids(clients, ids):
    books, creator = clients
    with pytest.raises(ValueError):
        sync_customer_numbers(books, creator, ids)
    assert not books.mock_calls and not creator.mock_calls


@pytest.mark.parametrize("rows", [[], [{"ID": "456", "Customer_Id": "123"}], [{"ID": "456", "Customer_Id": "123", "Customer_no": "WRONG"}], [{"ID": "456", "Customer_Id": "123", "Customer_no": ""}, {"ID": "789", "Customer_Id": "123", "Customer_no": ""}], [{"ID": "456", "Customer_Id": "123", "Customer_no": ""}, {"ID": "789", "Customer_Id": "999", "Customer_no": "CX123"}]])
def test_unsafe_creator_records(clients, rows):
    books, creator = clients
    creator.get_all_records.return_value = rows
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123"], dry_run=False)
    creator.update_records.assert_not_called()


@pytest.mark.parametrize("changes", [{"contact_number": ""}, {"contact_type": "vendor"}, {"contact_id": "999"}])
def test_invalid_books_contact(clients, changes):
    books, creator = clients
    books.contacts.get.return_value["contact"].update(changes)
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123"], dry_run=False)
    creator.update_records.assert_not_called()


def test_entire_plan_before_writes(clients):
    books, creator = clients
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123", "999"], dry_run=False)
    creator.update_records.assert_not_called()


@pytest.mark.parametrize("response", [{"code": 3001}, {"code": 3000, "result": [{"code": 3001}]}])
def test_update_rejection(clients, response):
    books, creator = clients
    creator.update_records.return_value = response
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123"], dry_run=False)
    creator.get_records.assert_not_called()


def test_failed_readback(clients):
    books, creator = clients
    creator.get_records.return_value["data"][0]["Customer_no"] = ""
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123"], dry_run=False)


def test_duplicate_planned_numbers(clients):
    books, creator = clients
    creator.get_all_records.return_value.append({"ID": "789", "Customer_Id": "999", "Customer_no": ""})
    books.contacts.get.side_effect = [{"code": 0, "contact": {"contact_id": cid, "contact_type": "customer", "contact_number": "CX123"}} for cid in ("123", "999")]
    with pytest.raises(ReconciliationError):
        sync_customer_numbers(books, creator, ["123", "999"], dry_run=False)
    creator.update_records.assert_not_called()


@pytest.mark.parametrize("flags,expected", [([], True), (["--dry-run"], True), (["--apply"], False)])
def test_cli(monkeypatch, capsys, flags, expected):
    import sys
    from apps import sync_customer_numbers as app
    from workflows import CustomerNumberSyncResult
    run = Mock(return_value=CustomerNumberSyncResult(expected, [], 0, 0))
    monkeypatch.setattr(app, "sync_customer_numbers", run)
    monkeypatch.setattr(app, "get_books_client", Mock())
    monkeypatch.setattr(app, "get_creator_client", Mock())
    monkeypatch.setattr(sys, "argv", ["sync_customer_numbers.py", "--books-contact-id", "123", *flags])
    app.main()
    assert run.call_args.kwargs["dry_run"] is expected
    assert '"changes"' in capsys.readouterr().out
