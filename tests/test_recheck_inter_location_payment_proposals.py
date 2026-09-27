from types import SimpleNamespace

import pytest

from apps.recheck_inter_location_payment_proposals import recheck


class Payments:
    def __init__(self, records, wrapper):
        self.records = records
        self.wrapper = wrapper

    def get(self, payment_id):
        return {self.wrapper: self.records[payment_id]}


def proposal(payment_type, payment_id, status="proposed"):
    return {
        "payment_type": payment_type, "payment_id": payment_id,
        "date": "07/07/2025", "amount": "INR 100.00",
        "bank_account_id": "bank", "from_location_id": "old",
        "to_location_id": "new", "status": status,
    }


def record(payment_id, location, vendor=False):
    result = {"payment_id": payment_id, "location_id": location,
              "date": "2025-07-07", "amount": 100, "payment_number": "P-1"}
    result["paid_through_account_id" if vendor else "account_id"] = "bank"
    return result


def test_recheck_removes_only_payments_at_destination():
    books = SimpleNamespace(
        customer_payments=Payments({"1": record("1", "new"),
                                    "2": record("2", "old")}, "payment"),
        vendor_payments=Payments({"3": record("3", "other", True)}, "vendorpayment"),
    )
    remaining, audit = recheck(books, [proposal("Customer Payment", "1"),
                                     proposal("Customer Payment", "2"),
                                     proposal("Vendor Payment", "3")])
    assert [p["payment_id"] for p in remaining] == ["2", "3"]
    assert [item["state"] for item in audit] == [
        "already_updated", "outstanding", "changed_location_review"]
    assert remaining[1]["status"] == "manual_review"


def test_recheck_keeps_changed_details_for_review():
    changed = record("1", "new")
    changed["amount"] = 101
    books = SimpleNamespace(customer_payments=Payments({"1": changed}, "payment"))
    remaining, audit = recheck(books, [proposal("Customer Payment", "1")])
    assert remaining[0]["status"] == "manual_review"
    assert audit[0]["state"] == "changed_details"


def test_recheck_holds_destination_number_with_source_location():
    payment = record("1", "old", True)
    payment["payment_number"] = "BL2526VP-00009"
    books = SimpleNamespace(vendor_payments=Payments({"1": payment}, "vendorpayment"))
    candidate = proposal("Vendor Payment", "1")
    candidate["expected_number_prefix"] = "BL2526VP-"
    remaining, audit = recheck(books, [candidate])
    assert audit[0]["state"] == "destination_number_source_location"
    assert remaining[0]["status"] == "manual_review"


def test_recheck_rejects_duplicate_payment():
    books = SimpleNamespace(customer_payments=Payments({"1": record("1", "old")}, "payment"))
    with pytest.raises(ValueError, match="Duplicate payment"):
        recheck(books, [proposal("Customer Payment", "1"),
                        proposal("Customer Payment", "1")])
