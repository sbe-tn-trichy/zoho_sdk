import pytest

from workflows.inter_location_split_proposals import propose_split


def candidate():
    return {"payment_type": "Customer Payment", "payment_id": "p1",
            "financial_year": "FY 2025-26"}


def payment():
    return {"payment_id": "p1", "payment_number": "SBE2526CP-1",
            "date": "2026-03-30", "amount": 25000, "unused_amount": 0,
            "location_id": "1094368000000443455", "location_name": "Sri Bharath Electricals",
            "invoices": [{"invoice_id": "a", "amount_applied": 22940},
                         {"invoice_id": "b", "amount_applied": 2060}]}


def documents():
    return [{"invoice_id": "a", "invoice_number": "SBE-1",
             "location_id": "1094368000000443455", "location_name": "Sri Bharath Electricals"},
            {"invoice_id": "b", "invoice_number": "SB-1",
             "location_id": "1094368000044509446", "location_name": "SBE"}]


def test_split_proposes_exact_retain_and_create_amounts():
    result = propose_split(candidate(), payment(), documents())
    assert result["status"] == "split_proposed"
    assert result["retain"]["amount"] == "22940.00"
    assert result["create"][0]["amount"] == "2060.00"
    assert result["create"][0]["observed_number_prefix"] == "SB2526CP-"


def test_split_holds_partially_allocated_payment():
    source = payment()
    source["amount"] = 26000
    result = propose_split(candidate(), source, documents())
    assert result["status"] == "manual_review"
    assert result["create"] == []


def test_split_rejects_missing_source_document():
    with pytest.raises(ValueError, match="Document count differs"):
        propose_split(candidate(), payment(), documents()[:1])
