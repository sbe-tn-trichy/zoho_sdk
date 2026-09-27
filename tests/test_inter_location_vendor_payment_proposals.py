from unittest.mock import Mock

import pytest

from workflows.inter_location_vendor_payment_proposals import propose_vendor_payment_moves


def proposal():
    return {"status": "proposed", "payment_type": "Vendor Payment",
            "financial_year": "FY 2025-26", "payment_id": "v", "date": "20/02/2026",
            "amount": "INR 2,000.00", "bank_account_id": "bank",
            "from_location_id": "old", "to_location_id": "new",
            "document_numbers": ["B-1"], "expected_number_prefix": "SB2526VP-"}


def books():
    client = Mock()
    client.vendor_payments.list.return_value = {
        "vendorpayments": [{"payment_number": "SB2526VP-00064"}],
        "page_context": {"sort_column": "payment_number", "sort_order": "D",
                         "search_criteria": [{"column_name": "payment_number",
                                              "search_text": "SB2526VP-", "comparator": "startswith"}]}}
    client.vendor_payments.get.return_value = {"vendorpayment": {
        "payment_id": "v", "location_id": "old", "paid_through_account_id": "bank",
        "date": "2026-02-20", "amount": 2000, "payment_number": "SBE2526VP-00200",
        "bills": [{"bill_id": "b"}]}}
    client.bills.get.return_value = {"bill": {"location_id": "new", "bill_number": "B-1"}}
    return client


def test_proposes_next_number_after_books_bill_preflight():
    client = books()
    moves, held = propose_vendor_payment_moves(client, [proposal()])
    assert not held
    assert moves[0]["destination_number"] == "SB2526VP-00065"
    client.vendor_payments.update.assert_not_called()


def test_excludes_existing_destination_series_number_without_consuming_suffix():
    client = books()
    client.vendor_payments.get.return_value["vendorpayment"]["payment_number"] = "SB2526VP-00009"
    first = proposal()
    second = {**proposal(), "payment_id": "v2", "date": "21/02/2026"}
    client.vendor_payments.get.side_effect = [client.vendor_payments.get.return_value,
        {"vendorpayment": {**client.vendor_payments.get.return_value["vendorpayment"],
                           "payment_id": "v2", "date": "2026-02-21",
                           "payment_number": "OTHER-00001"}}]
    moves, held = propose_vendor_payment_moves(client, [first, second])
    assert not held
    assert [move["destination_number"] for move in moves] == ["SB2526VP-00065"]


def test_holds_stale_payment_and_bill_location():
    client = books()
    client.vendor_payments.get.return_value["vendorpayment"]["location_id"] = "new"
    moves, held = propose_vendor_payment_moves(client, [proposal()])
    assert not moves and not held
    client = books()
    client.bills.get.return_value["bill"]["location_id"] = "old"
    moves, held = propose_vendor_payment_moves(client, [proposal()])
    assert not moves and "bill location" in held[0]["reason"]


def test_rejects_ignored_series_filter():
    client = books()
    client.vendor_payments.list.return_value["page_context"]["search_criteria"] = []
    with pytest.raises(ValueError, match="did not confirm"):
        propose_vendor_payment_moves(client, [proposal()])
