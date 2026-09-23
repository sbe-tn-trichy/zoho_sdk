from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from workflows.bill_updates import update_bill_with_payment_reallocation


class Bills:
    def __init__(self):
        self.bill = {"bill_id": "b1", "vendor_id": "v1", "total": 110.0,
                     "payments": [{"payment_id": "p1"}]}
        self.events = []

    def get(self, _):
        return {"bill": deepcopy(self.bill)}

    def update(self, _, payload):
        self.events.append("bill")
        self.bill["total"] = payload["new_total"]


class Payments:
    def __init__(self):
        self.payment = {"payment_id": "p1", "vendor_id": "v1", "amount": 150.0,
                        "bills": [
                            {"bill_id": "b1", "bill_payment_id": "a1", "amount_applied": 110.0},
                            {"bill_id": "b2", "bill_payment_id": "a2", "amount_applied": 40.0},
                        ]}
        self.events = []

    def get(self, _):
        return {"vendorpayment": deepcopy(self.payment)}

    def update(self, _, payload):
        self.events.append([row["bill_id"] for row in payload["bills"]])
        assert payload["amount"] == 150.0
        self.payment["bills"] = deepcopy(payload["bills"])


@pytest.fixture
def books():
    return SimpleNamespace(bills=Bills(), vendor_payments=Payments())


def test_decrease_detaches_updates_and_reapplies_with_credit(books):
    result = update_bill_with_payment_reallocation(
        books, "b1", {"new_total": 100.0}, expected_total=Decimal("100.00"), dry_run=False,
    )
    assert books.vendor_payments.events == [["b1", "b2"], ["b2", "b1"]]
    assert books.vendor_payments.payment["bills"][0]["amount_applied"] == 40.0
    assert books.bills.events == ["bill"]
    assert books.vendor_payments.payment["bills"][-1]["amount_applied"] == 100.0
    assert result.unapplied_credit == Decimal("10.00")


def test_increase_updates_directly(books):
    result = update_bill_with_payment_reallocation(
        books, "b1", {"new_total": 120.0}, expected_total=Decimal("120.00"), dry_run=False,
    )
    assert books.vendor_payments.events == []
    assert books.bills.events == ["bill"]
    assert result.unapplied_credit == Decimal("0.00")


def test_default_dry_run_makes_no_changes(books):
    result = update_bill_with_payment_reallocation(
        books, "b1", {"new_total": 100.0}, expected_total=Decimal("100.00"),
    )
    assert result.dry_run
    assert books.vendor_payments.events == []
    assert books.bills.events == []


def test_bill_failure_restores_original_payment_allocation(books):
    def fail_update(_bill_id, _payload):
        raise RuntimeError("Books rejected bill")

    books.bills.update = fail_update
    with pytest.raises(RuntimeError, match="Books rejected bill"):
        update_bill_with_payment_reallocation(
            books, "b1", {"new_total": 100.0},
            expected_total=Decimal("100.00"), dry_run=False,
        )
    target = [row for row in books.vendor_payments.payment["bills"] if row["bill_id"] == "b1"]
    assert len(target) == 1
    assert target[0]["amount_applied"] == 110.0


def test_rejects_negative_target_without_mutation(books):
    with pytest.raises(ValueError, match="negative"):
        update_bill_with_payment_reallocation(
            books, "b1", {"new_total": -1.0},
            expected_total=Decimal("-1.00"), dry_run=False,
        )
    assert books.vendor_payments.events == []
