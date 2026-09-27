from unittest.mock import Mock

import pytest

from workflows.inter_location_payment_updates import (
    apply_customer_payment_move, plan_customer_payment_moves, verify_customer_payment_batch,
)


def proposal():
    return {"status": "proposed", "payment_type": "Customer Payment",
            "payment_id": "p", "date": "31/03/2026", "amount": "INR 4,600.00",
            "bank_account_id": "bank", "from_location_id": "old", "to_location_id": "sbe",
            "document_numbers": ["INV"], "expected_number_prefix": "SBE2526CP-"}


def books():
    client = Mock()
    client.customer_payments.list.return_value = {
        "customer_payments": [{"payment_id": "old", "payment_number": "SBE2526CP-03380"}],
        "page_context": {"sort_column": "payment_number", "sort_order": "D",
                         "search_criteria": [{"column_name": "payment_number",
                                              "search_text": "SBE2526CP-", "comparator": "startswith"}]}}
    client.customer_payments.get.return_value = {"payment": {
        "payment_id": "p", "location_id": "old", "account_id": "bank",
        "date": "2026-03-31", "amount": 4600, "payment_number": "SB2627CP-00063",
        "invoices": [{"invoice_id": "i"}]}}
    client.invoices.get.return_value = {"invoice": {"location_id": "sbe", "invoice_number": "INV"}}
    return client


def test_plan_checks_books_and_next_number():
    client = books()
    moves = plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)
    assert moves[0]["new_number"] == "SBE2526CP-03381"
    client.customer_payments.update.assert_not_called()


def test_plan_skips_stale_location_and_rejects_stale_suffix():
    client = books()
    client.customer_payments.get.return_value["payment"]["location_id"] = "sbe"
    assert plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380) == []
    client = books()
    client.customer_payments.list.return_value["customer_payments"][0]["payment_number"] = "SBE2526CP-03381"
    with pytest.raises(ValueError, match="stale"):
        plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)


def test_plan_rejects_ignored_series_filter():
    client = books()
    client.customer_payments.list.return_value["page_context"]["search_criteria"] = []
    with pytest.raises(ValueError, match="did not confirm"):
        plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-")


def test_apply_requires_exact_readback():
    client = books()
    move = plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)[0]
    after = dict(client.customer_payments.get.return_value["payment"])
    after.update(location_id="sbe", payment_number="SBE2526CP-03381")
    client.customer_payments.get.side_effect = [client.customer_payments.get.return_value, {"payment": after}]
    client.customer_payments.update_with_number_series.return_value = {"code": 0}
    assert apply_customer_payment_move(client, move)["status"] == "verified"
    client.customer_payments.update_with_number_series.assert_called_once_with("p", {
        "location_id": "sbe", "payment_number_prefix": "SBE2526CP-",
        "payment_number_suffix": "03381"})


def test_apply_stops_on_unexpected_saved_number():
    client = books()
    move = plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)[0]
    client.customer_payments.update_with_number_series.return_value = {"code": 0}
    with pytest.raises(ValueError, match="Post-update verification failed"):
        apply_customer_payment_move(client, move)


def test_batch_readback_uses_one_descending_series_page():
    client = books()
    move = plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)[0]
    client.customer_payments.list.reset_mock()
    client.customer_payments.list.return_value["customer_payments"] = [{
        "payment_id": "p", "payment_number": "SBE2526CP-03381", "location_id": "sbe",
        "account_id": "bank", "date": "2026-03-31", "amount": 4600}]
    assert verify_customer_payment_batch(client, [move])[0]["status"] == "verified"
    client.customer_payments.list.assert_called_once_with({
        "payment_number_startswith": "SBE2526CP-", "sort_column": "payment_number",
        "sort_order": "D", "page": 1, "per_page": 1})
    client.customer_payments.get.assert_called_once_with("p")  # preflight only


def test_batch_readback_rejects_missing_payment():
    client = books()
    move = plan_customer_payment_moves(client, [proposal()], prefix="SBE2526CP-", last_suffix=3380)[0]
    client.customer_payments.list.return_value["customer_payments"] = []
    with pytest.raises(ValueError, match="did not return all"):
        verify_customer_payment_batch(client, [move])
