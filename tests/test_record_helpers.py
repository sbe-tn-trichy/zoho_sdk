"""Detail-envelope and identity guarantees for generic resource reads."""

from unittest.mock import Mock

import pytest

from zoho.helpers import get_verified_record
from zoho.helpers.records import get_verified_record as direct_helper


@pytest.mark.parametrize("key,id_key", [
    ("invoice", "invoice_id"), ("bill", "bill_id"),
    ("vendor_credit", "vendor_credit_id"), ("journal", "journal_id"),
    ("payment", "payment_id"),
])
def test_verified_record_preserves_detail(key, id_key):
    record = {id_key: "123", "amount": 10}
    resource = Mock()
    resource.get.return_value = {key: record}
    assert get_verified_record(resource, identifier="123", key=key, id_key=id_key) is record
    resource.get.assert_called_once_with("123")
    assert get_verified_record is direct_helper


def test_numeric_response_id():
    resource = Mock()
    resource.get.return_value = {"bill": {"bill_id": 123}}
    assert get_verified_record(resource, "123", "bill", "bill_id") == {"bill_id": 123}


@pytest.mark.parametrize("response", [
    None, [], "invalid", {}, {"bill": None}, {"bill": []},
    {"bill": {}}, {"bill": {"bill_id": None}},
    {"bill": {"bill_id": "other"}},
])
def test_invalid_detail_fails(response):
    resource = Mock()
    resource.get.return_value = response
    with pytest.raises(ValueError, match="invalid bill detail for 123"):
        get_verified_record(resource, "123", "bill", "bill_id")


def test_missing_id_cannot_match_none_string():
    resource = Mock()
    resource.get.return_value = {"bill": {}}
    with pytest.raises(ValueError):
        get_verified_record(resource, "None", "bill", "bill_id")


def test_resource_error_propagates():
    resource = Mock()
    error = RuntimeError("request failed")
    resource.get.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        get_verified_record(resource, "123", "bill", "bill_id")
    assert caught.value is error
