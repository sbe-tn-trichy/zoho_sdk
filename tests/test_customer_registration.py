from copy import deepcopy
from unittest.mock import Mock

import pytest

from workflows import CustomerRegistrationError, register_customer
from apps.register_customer import json_object


@pytest.fixture
def clients():
    books, creator = Mock(), Mock()
    books.contacts.create.return_value = {"code": 0, "contact": {"contact_id": "123", "contact_number": "CX123"}}
    books.contacts.get.return_value = {"code": 0, "contact": {"contact_id": "123", "contact_type": "customer", "contact_number": "CX123"}}
    creator.add_records.return_value = {"code": 3000, "result": [{"code": 3000, "data": {"ID": "456"}}]}
    return books, creator


def test_create_both_and_preserve_inputs(clients):
    books, creator = clients
    data = {"Customer_Name": "Example", "Beat": "789"}
    books_data = {"billing_address": {"city": "Test"}}
    original = deepcopy((data, books_data))
    result = register_customer(books, creator, data, books_data=books_data)
    assert result.books_contact_id == "123"
    assert result.creator_record_id == "456"
    books.contacts.create.assert_called_once_with({"contact_name": "Example", "contact_type": "customer", **books_data})
    creator.add_records.assert_called_once_with("order-management-new", "Customer_Registration", payload={
        "data": [{**data, "Customer_Id": "123", "Customer_no": "CX123"}], "skip_workflow": ["all"]})
    assert (data, books_data) == original


def test_preview_no_network(clients):
    books, creator = clients
    result = register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=True)
    assert result.dry_run
    assert result.books_contact_id is None
    assert not books.mock_calls and not creator.mock_calls


@pytest.mark.parametrize("data,kwargs", [
    ({}, {}), ({"Customer_Name": " "}, {}),
    ({"Customer_Name": "Example", "Customer_Id": "123"}, {}),
    ({"Customer_Name": "Example"}, {"books_data": {"contact_type": "vendor"}}),
    ({"Customer_Name": "Example"}, {"books_data": {"contact_name": ""}}),
    ({"Customer_Name": "Example"}, {"existing_books_contact_id": " "}),
    ({"Customer_Name": "Example"}, {"form_link_name": ""}),
])
def test_validation_before_writes(clients, data, kwargs):
    books, creator = clients
    with pytest.raises(ValueError):
        register_customer(books, creator, data, dry_run=False, **kwargs)
    assert not books.mock_calls and not creator.mock_calls


@pytest.mark.parametrize("response", [{"code": 1}, {"code": 0, "contact": {}}])
def test_books_failure_stops_creator(clients, response):
    books, creator = clients
    books.contacts.create.return_value = response
    with pytest.raises(CustomerRegistrationError):
        register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=False)
    creator.add_records.assert_not_called()


def test_books_exception_stops_creator(clients):
    books, creator = clients
    books.contacts.create.side_effect = RuntimeError("network")
    with pytest.raises(RuntimeError):
        register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=False)
    creator.add_records.assert_not_called()


@pytest.mark.parametrize("response", [
    {"code": 3001}, {"code": 3000, "result": []},
    {"code": 3000, "result": [{"code": 3001, "data": {"ID": "456"}}]},
    {"code": 3000, "data": {}},
])
def test_creator_rejection_carries_books_id(clients, response):
    books, creator = clients
    creator.add_records.return_value = response
    with pytest.raises(CustomerRegistrationError) as error:
        register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=False)
    assert error.value.books_contact_id == "123"
    books.contacts.delete.assert_not_called()


def test_creator_exception_carries_books_id(clients):
    books, creator = clients
    creator.add_records.side_effect = RuntimeError("timeout")
    with pytest.raises(CustomerRegistrationError) as error:
        register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=False)
    assert error.value.books_contact_id == "123"


def test_recovery_reuses_verified_customer(clients):
    books, creator = clients
    result = register_customer(books, creator, {"Customer_Name": "Example", "Customer_Id": "123"},
                               existing_books_contact_id="123", dry_run=False)
    books.contacts.get.assert_called_once_with("123")
    books.contacts.create.assert_not_called()
    assert result.creator_record_id == "456"


def test_recovery_rejects_vendor(clients):
    books, creator = clients
    books.contacts.get.return_value["contact"]["contact_type"] = "vendor"
    with pytest.raises(CustomerRegistrationError):
        register_customer(books, creator, {"Customer_Name": "Example"}, existing_books_contact_id="123", dry_run=False)
    creator.add_records.assert_not_called()


def test_single_record_response(clients):
    books, creator = clients
    creator.add_records.return_value = {"code": 3000, "data": {"ID": "456"}}
    assert register_customer(books, creator, {"Customer_Name": "Example"}, dry_run=False).creator_record_id == "456"


def test_json_requires_object():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        json_object("[]")


def test_app_constructs_both_clients(monkeypatch, clients):
    from apps import register_customer as app
    books, creator = clients
    monkeypatch.setattr(app, "get_books_client", lambda: books)
    monkeypatch.setattr(app, "get_creator_client", lambda: creator)
    result = app.create_customer_record({"Customer_Name": "Example"})
    assert result["books_contact_id"] == "123"
    assert result["creator_record_id"] == "456"


@pytest.mark.parametrize("flags,expected", [([], False), (["--dry-run"], True), (["--apply"], False)])
def test_cli_create_modes(monkeypatch, capsys, flags, expected):
    import sys
    from apps import register_customer as app
    create = Mock(return_value={"dry_run": expected})
    monkeypatch.setattr(app, "create_customer_record", create)
    monkeypatch.setattr(sys, "argv", ["register_customer.py", "create", '{"Customer_Name":"Example"}', *flags])
    app.main()
    assert create.call_args.kwargs["dry_run"] is expected
    assert '"dry_run"' in capsys.readouterr().out


def test_cli_missing_data_is_error(monkeypatch):
    import sys
    from apps import register_customer as app
    monkeypatch.setattr(sys, "argv", ["register_customer.py", "create"])
    with pytest.raises(SystemExit) as error:
        app.main()
    assert error.value.code == 2


def test_live_registration_name_field(clients):
    books, creator = clients
    result = register_customer(books, creator, {"Name": "Example"})
    assert result.books_payload["contact_name"] == "Example"
    assert result.creator_payload["data"][0]["Name"] == "Example"
    assert "Customer_Name" not in result.creator_payload["data"][0]


def test_blank_name_does_not_fall_back_to_legacy(clients):
    books, creator = clients
    with pytest.raises(ValueError):
        register_customer(books, creator, {"Name": "", "Customer_Name": "Example"})
    assert not books.mock_calls and not creator.mock_calls


def test_number_falls_back_to_books_detail(clients):
    books, creator = clients
    del books.contacts.create.return_value["contact"]["contact_number"]
    result = register_customer(books, creator, {"Name": "Example", "Customer_no": "WRONG"})
    books.contacts.get.assert_called_once_with("123")
    assert result.books_contact_number == "CX123"
    assert result.creator_payload["data"][0]["Customer_no"] == "CX123"


@pytest.mark.parametrize("number", [None, "", " "])
def test_missing_books_number_stops_creator(clients, number):
    books, creator = clients
    books.contacts.create.return_value["contact"]["contact_number"] = number
    books.contacts.get.return_value["contact"]["contact_number"] = number
    with pytest.raises(CustomerRegistrationError) as error:
        register_customer(books, creator, {"Name": "Example"})
    assert error.value.books_contact_id == "123"
    creator.add_records.assert_not_called()


def test_number_lookup_failure_carries_books_id(clients):
    books, creator = clients
    del books.contacts.create.return_value["contact"]["contact_number"]
    books.contacts.get.side_effect = RuntimeError("network")
    with pytest.raises(CustomerRegistrationError) as error:
        register_customer(books, creator, {"Name": "Example"})
    assert error.value.books_contact_id == "123"
    creator.add_records.assert_not_called()
