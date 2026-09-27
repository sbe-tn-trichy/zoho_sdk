from unittest.mock import Mock

import pytest

from workflows.apply_inter_location_updates import apply_verified_move, verify_proposed_pair


def proposal():
    return {"status": "proposed", "matching_evidence": "Exact reference",
            "customer_payment_id": "cp", "contra_id": "vp", "contra_type": "Vendor Payment",
            "date": "01/01/2026", "amount": "INR 10.00", "invoice_numbers": ["INV"],
            "bill_numbers": ["BILL"], "moves": [{"transaction_type": "customer_payment",
            "transaction_id": "cp", "from_location_id": "a", "to_location_id": "b"}]}


def books(invoice_location="b"):
    result = Mock()
    result.customer_payments.get.return_value = {"payment": {
        "payment_id": "cp", "account_id": "1094368000002033114", "location_id": "a",
        "date": "2026-01-01", "amount": 10, "reference_number": "ref",
        "invoices": [{"invoice_id": "i"}]}}
    result.vendor_payments.get.return_value = {"vendorpayment": {
        "payment_id": "vp", "paid_through_account_id": "1094368000002033114",
        "location_id": "b", "date": "2026-01-01", "amount": 10,
        "reference_number": "ref", "bills": [{"bill_id": "x"}]}}
    result.invoices.get.return_value = {"invoice": {"invoice_number": "INV", "location_id": invoice_location}}
    result.bills.get.return_value = {"bill": {"bill_number": "BILL", "location_id": "b"}}
    return result


def test_preflight_checks_documents_without_update():
    client = books()
    verified = verify_proposed_pair(client, proposal())
    assert verified["to_location_id"] == "b"
    client.customer_payments.update.assert_not_called()


def test_preflight_blocks_changed_invoice_location():
    with pytest.raises(ValueError, match="Invoice location changed"):
        verify_proposed_pair(books(invoice_location="a"), proposal())


def test_apply_updates_location_only_and_verifies_pair():
    client = books()
    verified = verify_proposed_pair(client, proposal())
    after = dict(client.customer_payments.get.return_value["payment"])
    after["location_id"] = "b"
    client.customer_payments.get.side_effect = [client.customer_payments.get.return_value, {"payment": after}]
    client.customer_payments.update.return_value = {"code": 0}
    result = apply_verified_move(client, verified)
    client.customer_payments.update.assert_called_once_with("cp", {"location_id": "b"})
    assert result["status"] == "moved"
