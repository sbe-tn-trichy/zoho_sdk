from unittest.mock import Mock

import pytest

from workflows.inter_location_vendor_payment_updates import (
    preflight_vendor_moves, submit_vendor_move, verify_vendor_batch,
)


def move():
    return {"payment_id": "v", "date": "2026-02-27", "amount": "100000",
            "bank_account_id": "bank", "old_number": "SBE2526VP-00212",
            "destination_number": "SB2526VP-00066", "from_location_id": "old",
            "to_location_id": "new", "bill_numbers": ["B-1"]}


def books():
    client = Mock()
    client.vendor_payments.list.return_value = {
        "vendorpayments": [{"payment_number": "SB2526VP-00064"}],
        "page_context": {"sort_column": "payment_number", "sort_order": "D",
                         "search_criteria": [{"column_name": "payment_number",
                                              "search_text": "SB2526VP-", "comparator": "startswith"}]}}
    client.vendor_payments.get.return_value = {"vendorpayment": {
        "payment_id": "v", "payment_number": "SBE2526VP-00212", "location_id": "old",
        "paid_through_account_id": "bank", "date": "2026-02-27", "amount": 100000,
        "bills": [{"bill_id": "b"}]}}
    client.bills.get.return_value = {"bill": {"location_id": "new", "bill_number": "B-1"}}
    return client


def test_preflight_and_submit_single_multipart_update():
    client = books()
    preflight_vendor_moves(client, [move()])
    client.vendor_payments.update_with_number_series.return_value = {"code": 0}
    submit_vendor_move(client, move())
    client.vendor_payments.update_with_number_series.assert_called_once_with("v", {
        "location_id": "new", "payment_number_prefix": "SB2526VP-",
        "payment_number_suffix": "00066"})


def test_preflight_blocks_changed_bill_and_colliding_number():
    client = books()
    client.bills.get.return_value["bill"]["location_id"] = "old"
    with pytest.raises(ValueError, match="bill location changed"):
        preflight_vendor_moves(client, [move()])
    client = books()
    client.vendor_payments.list.return_value["vendorpayments"][0]["payment_number"] = "SB2526VP-00066"
    with pytest.raises(ValueError, match="collide"):
        preflight_vendor_moves(client, [move()])


def test_one_batch_readback_matches_all_saved_fields():
    client = books()
    client.vendor_payments.list.return_value["vendorpayments"] = [{
        "payment_id": "v", "payment_number": "SB2526VP-00066", "location_id": "new",
        "paid_through_account_id": "bank", "date": "2026-02-27", "amount": 100000}]
    assert verify_vendor_batch(client, [move()])[0]["status"] == "verified"
    client.vendor_payments.list.assert_called_once()
    client.vendor_payments.list.return_value["vendorpayments"][0]["location_id"] = "old"
    with pytest.raises(ValueError, match="read-back mismatch"):
        verify_vendor_batch(client, [move()])
