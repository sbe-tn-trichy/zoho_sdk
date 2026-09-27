import json
from unittest.mock import Mock

import pytest

from zoho.books.resources.sales import CustomerPayments
from zoho.books.resources.purchases import VendorPayments


def test_multipart_series_update_uses_jsonstring_and_ignore_flag():
    client = Mock()
    resource = CustomerPayments(client)
    payload = {"location_id": "loc", "payment_number_prefix": "SB2526CP-",
               "payment_number_suffix": "00011"}
    resource.update_with_number_series("payment", payload)
    args, kwargs = client.request.call_args
    assert args == ("PUT", "customerpayments/payment")
    assert json.loads(kwargs["files"]["JSONString"][1]) == payload
    assert kwargs["files"]["ignore_auto_number_generation"] == (None, "true")


def test_multipart_series_update_requires_number_and_location():
    resource = CustomerPayments(Mock())
    with pytest.raises(ValueError, match="destination location"):
        resource.update_with_number_series("payment", {"payment_number_prefix": "x", "payment_number_suffix": "1"})
    with pytest.raises(ValueError, match="prefix and suffix"):
        resource.update_with_number_series("payment", {"location_id": "loc"})


def test_vendor_multipart_series_update_uses_ignore_flag():
    client = Mock()
    payload = {"location_id": "loc", "payment_number_prefix": "SB2526VP-",
               "payment_number_suffix": "00066"}
    VendorPayments(client).update_with_number_series("vendor", payload)
    args, kwargs = client.request.call_args
    assert args == ("PUT", "vendorpayments/vendor")
    assert json.loads(kwargs["files"]["JSONString"][1]) == payload
    assert kwargs["files"]["ignore_auto_number_generation"] == (None, "true")
