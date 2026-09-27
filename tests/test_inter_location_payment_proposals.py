import pytest

from workflows.inter_location_payment_proposals import (
    allocation_summary_query, expected_payment_prefix, filter_payment_rows_for_year,
    propose_payment_locations,
)


def test_filters_current_fiscal_year_out_of_last_year_proposal():
    old = row(**{"Financial Year": "FY 2025-26"})
    current = row(**{"Financial Year": "FY 2026-27"})
    assert filter_payment_rows_for_year([old, current], "FY 2025-26") == [old]
    with pytest.raises(ValueError, match="Unsupported financial year"):
        filter_payment_rows_for_year([old], "FY 2024-25")


def row(**changes):
    base = {"Issue Type": "Customer payment vs invoice", "Debit Type": "Customer Payment",
            "Debit Transaction ID": "p1", "Date": "01/05/2026", "Financial Year": "FY 2026-27",
            "Amount": "INR 100.00", "Bank Account ID": "bank", "Bank Account Name": "Bank",
            "Debit Location ID": "old", "Debit Location": "Old",
            "Credit Location ID": "new", "Credit Location": "New", "Credit Reference": "INV-1"}
    return {**base, **changes}


def summary(*, low="new", high="new", allocated="2", found="2"):
    return {"Customer Payment": {"p1": {"Min Document Location ID": low,
            "Max Document Location ID": high, "Allocation Count": allocated, "Found Count": found}}}


def test_proposes_only_when_all_allocations_agree():
    proposals = propose_payment_locations([row(), row(**{"Credit Reference": "INV-2"})], summary())
    assert len(proposals) == 1
    assert proposals[0]["status"] == "proposed"
    assert proposals[0]["document_numbers"] == ["INV-1", "INV-2"]


@pytest.mark.parametrize("summaries", [summary(high="old"), summary(found="1"), {}])
def test_holds_mixed_missing_or_unavailable_allocations(summaries):
    assert propose_payment_locations([row()], summaries)[0]["status"] == "manual_review"


def test_holds_clearing_account_and_rejects_conflicting_rows():
    clearing = row(**{"Bank Account ID": "1094368000002033114"})
    assert propose_payment_locations([clearing], summary())[0]["status"] == "manual_review"
    with pytest.raises(ValueError, match="Conflicting"):
        propose_payment_locations([row(), row(**{"Amount": "INR 200.00"})], summary())


def test_summary_queries_cover_all_allocations():
    customer = allocation_summary_query("Customer Payment")
    vendor = allocation_summary_query("Vendor Payment")
    assert 'COUNT(IP."Invoice ID")' in customer
    assert 'COUNT(B."Bill ID")' in vendor
    assert '"Location ID" <>' not in customer + vendor
    with pytest.raises(ValueError, match="Unsupported"):
        allocation_summary_query("Other")


def test_number_prefix_follows_destination_fiscal_year_and_payment_type():
    assert expected_payment_prefix("1094368000000443455", "FY 2025-26", "Customer Payment") == "SBE2526CP-"
    assert expected_payment_prefix("1094368000044509446", "FY 2026-27", "Vendor Payment") == "SB2627VP-"
    assert expected_payment_prefix("unknown", "FY 2026-27", "Customer Payment") == ""
