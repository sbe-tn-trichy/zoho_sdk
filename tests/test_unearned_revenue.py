from decimal import Decimal
from unittest.mock import Mock

import pytest

from workflows import find_unused_customer_payments
from workflows.core.exceptions import ReconciliationError


def client(**changes):
    books = Mock()
    books.chart_of_accounts.get.return_value = {"code": 0, "chart_of_account": {
        "account_id": "1094368000000000617", "account_name": "Unearned Revenue"}}
    payment = dict(payment_id="p1", customer_id="c1", customer_name="Customer",
                   currency_code="INR", amount="100", unused_amount="25") | changes
    books.customer_payments.list_all.return_value = [{"payment_id": "p1", "customer_id": "c1"}]
    books.customer_payments.get.return_value = {"code": 0, "payment": payment}
    return books


def test_unused_balances_and_read_only_calls():
    books = client()
    report = find_unused_customer_payments(books, request_interval=0)
    assert report.totals_by_currency == {"INR": Decimal("25")}
    assert report.payments_checked == 1
    assert report.payments[0].customer_id == "c1"
    assert report.limitations
    assert [call[0] for call in books.mock_calls] == [
        "chart_of_accounts.get", "customer_payments.list_all", "customer_payments.get"]


@pytest.mark.parametrize("unused", ["0", "0.00"])
def test_fully_applied_payment(unused):
    report = find_unused_customer_payments(client(unused_amount=unused), request_interval=0)
    assert not report.payments and not report.totals_by_currency


@pytest.mark.parametrize("changes", [dict(unused_amount=None), dict(unused_amount="NaN"),
    dict(unused_amount=-1), dict(unused_amount=101), dict(amount="bad"),
    dict(currency_code=""), dict(customer_id="wrong"), dict(payment_id="wrong")])
def test_invalid_detail_fails_closed(changes):
    with pytest.raises(ReconciliationError):
        find_unused_customer_payments(client(**changes), request_interval=0)


def test_duplicate_and_failed_detail():
    books = client()
    books.customer_payments.list_all.return_value *= 2
    with pytest.raises(ReconciliationError, match="duplicate"):
        find_unused_customer_payments(books, request_interval=0)
    books = client()
    books.customer_payments.get.return_value = {"code": 5}
    with pytest.raises(ReconciliationError, match="Cannot read payment"):
        find_unused_customer_payments(books, request_interval=0)


def test_account_identity():
    books = client()
    books.chart_of_accounts.get.return_value["chart_of_account"]["account_id"] = "wrong"
    with pytest.raises(ReconciliationError, match="Account detail"):
        find_unused_customer_payments(books, request_interval=0)
    books.customer_payments.list_all.assert_not_called()


def test_currencies_are_not_combined():
    books = client()
    books.customer_payments.list_all.return_value.append({"payment_id": "p2", "customer_id": "c1"})
    first = books.customer_payments.get.return_value
    books.customer_payments.get.side_effect = [first, {"code": 0, "payment": {
        **first["payment"], "payment_id": "p2", "currency_code": "USD"}}]
    assert find_unused_customer_payments(books, request_interval=0).totals_by_currency == {
        "INR": Decimal(25), "USD": Decimal(25)}


def analytics_client(payments=None, postings=None):
    analytics = Mock()
    analytics.queries.execute.side_effect = [
        [{"Account ID": "1094368000000000617", "Account Name": "Unearned Revenue"}],
        payments if payments is not None else [{"Payment ID": "p1", "Customer ID": "c1",
            "Customer Name": "Customer", "Unused Amount (BCY)": "INR 25.00", "Amount (BCY)": "INR 100.00"}],
        postings if postings is not None else [{"Entity ID": "p1", "Entity Type": "payment",
            "Customer ID": "c1", "Credit": "100", "Debit": "75"}]]
    return analytics


def test_analytics_ledger_and_unused_balances():
    from workflows import review_unearned_revenue_analytics
    analytics = analytics_client()
    report = review_unearned_revenue_analytics(analytics, workspace_id="123")
    assert report["unused_payment_total_bcy"] == Decimal(25)
    assert report["account_net_credit_bcy"] == Decimal(25)
    assert report["ledger_less_unused_bcy"] == 0
    assert len(report["payments"][0]["account_entity_matches"]) == 1
    assert report["customers"][0]["unused_bcy"] == 25
    assert analytics.queries.execute.call_count == 3


@pytest.mark.parametrize("field,value", [("Unused Amount (BCY)", None),
    ("Unused Amount (BCY)", "NaN"), ("Unused Amount (BCY)", -1),
    ("Unused Amount (BCY)", 101), ("Payment ID", ""), ("Customer ID", "")])
def test_analytics_invalid_payments(field, value):
    from workflows import review_unearned_revenue_analytics
    row = {"Payment ID": "p1", "Customer ID": "c1", "Unused Amount (BCY)": 25,
           "Amount (BCY)": 100, field: value}
    with pytest.raises(ReconciliationError):
        review_unearned_revenue_analytics(analytics_client(payments=[row]), workspace_id="123")


def test_analytics_empty_payments_retains_journal_balance():
    from workflows import review_unearned_revenue_analytics
    report = review_unearned_revenue_analytics(analytics_client(payments=[], postings=[{
        "Entity ID": "j1", "Entity Type": "journal", "Credit": "10", "Debit": "0"}]), workspace_id="123")
    assert report["unused_payment_total_bcy"] == 0
    assert report["ledger_less_unused_bcy"] == 10
