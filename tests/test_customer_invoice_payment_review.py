from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from workflows.customer_invoice_payment_review import invoice_discount_percentage, review_customer_invoices_payments
from workflows.core.exceptions import ReconciliationError


@pytest.mark.parametrize("invoice,expected", [
    ({}, "0"), ({"discount": "3.00%"}, "3"),
    ({"discount_percent": 2}, "2"),
    ({"discount": 50, "discount_applied_on_amount": 1000}, "5"),
    ({"discount_total": 20, "line_items": [{"rate": 100, "quantity": 2}]}, "10"),
])
def test_discount(invoice, expected):
    assert invoice_discount_percentage(invoice) == Decimal(expected)


@pytest.mark.parametrize("invoice", [{"discount": "bad%"}, {"discount_percent": "NaN"}, {"discount": "101%"}, {"discount_total": 10}])
def test_invalid_discount(invoice):
    with pytest.raises(ReconciliationError):
        invoice_discount_percentage(invoice)


def client():
    books = MagicMock()
    books.contacts.get.return_value = {"code": 0, "contact": {"contact_id": "123", "contact_name": "Customer"}}
    books.invoices.list_all.return_value = [{"invoice_id": "i1"}, {"invoice_id": "i2"}]
    books.invoices.get.side_effect = [
        {"code": 0, "invoice": {"invoice_id": "i1", "customer_id": "123", "date": "2026-10-01", "invoice_number": "INV1", "total": 100, "discount": "3%", "payment_made": 70}},
        {"code": 0, "invoice": {"invoice_id": "i2", "customer_id": "123", "date": "2026-10-02", "invoice_number": "INV2", "total": 50, "payment_made": 0}},
    ]
    books.customer_payments.list_all.return_value = [{"payment_id": "p1"}, {"payment_id": "p2"}]
    books.customer_payments.get.side_effect = [
        {"code": 0, "payment": {"payment_id": "p1", "customer_id": "123", "date": "2026-10-03", "payment_number": "PAY1", "amount": 50, "unused_amount": 0, "invoices": [{"invoice_id": "i1", "amount_applied": 50}]}},
        {"code": 0, "payment": {"payment_id": "p2", "customer_id": "123", "date": "2026-10-04", "payment_number": "PAY2", "amount": 30, "unused_amount": 10, "invoices": [{"invoice_id": "i1", "amount_applied": 20}]}},
    ]
    return books


def test_partial_multiple_payments_and_unpaid_invoice():
    books = client()
    report = review_customer_invoices_payments(books, "123", request_interval=0)
    assert [row["payment"] for row in report.invoices] == [Decimal(70), Decimal(0)]
    assert [row["cd_applied"] for row in report.invoices] == [Decimal(3), Decimal(0)]
    assert report.allocations[1]["unused_amount"] == 10
    assert not report.issues
    books.invoices.list_all.assert_called_once_with(params={"customer_id": "123"})
    assert all(call[0].endswith(("get", "list_all")) for call in books.mock_calls)


def test_wrong_customer_stops_report():
    books = client()
    books.contacts.get.return_value["contact"]["contact_id"] = "999"
    with pytest.raises(ReconciliationError, match="different customer"):
        review_customer_invoices_payments(books, "123", request_interval=0)


def test_empty_customer():
    books = client()
    books.invoices.list_all.return_value = []
    books.customer_payments.list_all.return_value = []
    report = review_customer_invoices_payments(books, "123", request_interval=0)
    assert report.invoices == report.allocations == report.issues == []


def test_unallocated_payment_and_payment_total_discrepancy():
    books = client()
    payments = list(books.customer_payments.get.side_effect)
    payments[0]["payment"]["amount"] = 55
    payments[1]["payment"].update(invoices=[], unused_amount=30)
    books.customer_payments.get.side_effect = payments
    report = review_customer_invoices_payments(books, "123", request_interval=0)
    assert report.allocations[1]["invoice_number"] == ""
    assert report.allocations[1]["unused_amount"] == 30
    assert len(report.issues) == 2


def test_unknown_invoice_allocation_is_not_silently_dropped():
    books = client()
    payments = list(books.customer_payments.get.side_effect)
    payments[0]["payment"]["invoices"][0]["invoice_id"] = "unknown"
    books.customer_payments.get.side_effect = payments
    with pytest.raises(ReconciliationError, match="outside"):
        review_customer_invoices_payments(books, "123", request_interval=0)
