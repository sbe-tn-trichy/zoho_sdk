from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.inter_location_contra import (
    AccountEntry,
    add_analytics_location_evidence,
    fetch_account_entries,
    review_bank_payment_locations,
    review_contras,
    review_source_documents,
)


def row(transaction_id, direction, location, reference="CONTRA-1"):
    return AccountEntry(transaction_id, "journal", "2025-08-01", location, location,
                        direction, Decimal("125.50"), reference, transaction_id, "Contra")


def test_review_flags_only_unique_cross_location_pair():
    result = review_contras([row("1", "debit", "A"), row("2", "credit", "B"),
                             replace(row("3", "debit", "A", "SAME"), amount=Decimal("20")),
                             replace(row("4", "credit", "A", "SAME"), amount=Decimal("20"))])
    assert len(result["inter_location_contras"]) == 1
    assert result["inter_location_contras"][0]["review_status"] == "needs_review"
    assert result["inter_location_contras"][0]["proposed_move"] is None


def test_review_ambiguous_or_missing_location():
    result = review_contras([row("1", "debit", "A"), row("2", "credit", "B"),
                             row("3", "credit", "C"),
                             replace(row("4", "debit", "", "OTHER"), amount=Decimal("20")),
                             replace(row("5", "credit", "A", "OTHER"), amount=Decimal("20"))])
    assert not result["inter_location_contras"]
    assert len(result["ambiguous"]) == 2


def test_composite_reference_pairs_same_location_and_blank_reference_is_review_only():
    payment = row("P", "debit", "A", "2603003991")
    journal = row("J", "credit", "A", "2425CP-00034::2603003991")
    blank_debit = AccountEntry("C", "customer_payment", "2025-08-01", "A", "A",
                               "debit", Decimal("99.00"), "", "", "")
    blank_credit = AccountEntry("V", "vendor_payment", "2025-08-01", "B", "B",
                                "credit", Decimal("99.00"), "", "", "")
    review = review_contras([payment, journal, blank_debit, blank_credit])
    assert len(review["same_location_contras"]) == 1
    assert review["same_location_contras"][0]["matching_evidence"] == "embedded_reference"
    assert len(review["inter_location_contras"]) == 1
    assert review["inter_location_contras"][0]["matching_evidence"] == "date_amount_only"


def test_fetch_account_scoped_pages():
    books = SimpleNamespace(
        bank_transactions=SimpleNamespace(list=Mock(side_effect=[
            {"code": 0, "banktransactions": [{"transaction_id": "J1", "account_id": "ACCOUNT",
                "transaction_type": "journal", "date": "2025-08-01", "debit_or_credit": "debit",
                "amount": 125.5, "location_id": "LINE"}], "page_context": {"has_more_page": True}},
            {"code": 0, "banktransactions": [], "page_context": {"has_more_page": False}},
        ])),
    )
    entries = fetch_account_entries(books, "ACCOUNT", (("2025-04-01", "2026-03-31"),))
    assert len(entries) == 1
    assert entries[0].location_id == "LINE"
    assert books.bank_transactions.list.call_count == 2


def test_fetch_rejects_summary_only_response():
    books = SimpleNamespace(bank_transactions=SimpleNamespace(list=Mock(
        return_value={"code": 0, "transaction_list": [{"entity_type": "journal", "count": 2}]})))
    with pytest.raises(ValueError, match="did not return account transactions"):
        fetch_account_entries(books, "ACCOUNT")


def test_document_review_proposes_only_when_allocations_agree():
    review = review_contras([row("C", "debit", "A"), row("V", "credit", "B")])
    review["inter_location_contras"][0]["debit"]["transaction_type"] = "customer_payment"
    review["inter_location_contras"][0]["credit"]["transaction_type"] = "vendor_payment"
    review["account_id"] = "ACCOUNT"
    customer = {"payment": {"payment_id": "C", "account_id": "ACCOUNT", "reference_number": "CONTRA-1",
                            "location_id": "A", "invoices": [{"location_id": "B", "invoice_number": "I"}]}}
    vendor = {"vendorpayment": {"payment_id": "V", "paid_through_account_id": "ACCOUNT",
                                "reference_number": "CONTRA-1", "location_id": "B",
                                "bills": [{"bill_id": "B1"}]}}
    books = SimpleNamespace(customer_payments=SimpleNamespace(get=Mock(return_value=customer)),
                            vendor_payments=SimpleNamespace(get=Mock(return_value=vendor)),
                            bills=SimpleNamespace(get=Mock(return_value={"bill": {"location_id": "B", "bill_number": "BILL"}})))
    review_source_documents(books, review)
    doc_review = review["inter_location_contras"][0]["document_review"]
    assert doc_review["customer_payment_location"] == "A"
    assert doc_review["vendor_payment_location"] == "B"
    assert not doc_review["four_way_location_consistent"]
    assert review["inter_location_contras"][0]["proposed_move"]["to_location_id"] == "B"

    # When all 4 match
    customer["payment"]["location_id"] = "B"
    review_source_documents(books, review)
    doc_review_matched = review["inter_location_contras"][0]["document_review"]
    assert doc_review_matched["four_way_location_consistent"]

    # When allocations disagree
    customer["payment"]["invoices"][0]["location_id"] = "A"
    review_source_documents(books, review)
    assert review["inter_location_contras"][0]["proposed_move"] is None


def test_analytics_evidence_requires_exact_invoice_set():
    review = {"inter_location_contras": [{"document_review": {
        "customer_payment_number": "CP1", "invoice_numbers": ["I1", "I2"]}}]}
    add_analytics_location_evidence(review, [{"CP.Payment Number": "CP1", "INV.Invoice Number": "I1",
        "Payment Recorded Location": "SBE", "Invoice Location": "ZEISS"}])
    evidence = review["inter_location_contras"][0]["analytics_evidence"]
    assert evidence["matched_rows"] == 1
    assert not evidence["all_allocated_invoices_present"]


def test_review_bank_payment_locations():
    books = SimpleNamespace(
        bank_transactions=SimpleNamespace(list=Mock(return_value={
            "code": 0,
            "banktransactions": [
                {"transaction_id": "VP1", "account_id": "BANK1", "transaction_type": "vendor_payment",
                 "date": "2025-08-01", "debit_or_credit": "credit", "amount": 500.0, "location_id": "LOC_A", "location_name": "Branch A"},
                {"transaction_id": "CP1", "account_id": "BANK1", "transaction_type": "customer_payment",
                 "date": "2025-08-02", "debit_or_credit": "debit", "amount": 300.0, "location_id": "LOC_B", "location_name": "Branch B"},
            ],
            "page_context": {"has_more_page": False},
        })),
        vendor_payments=SimpleNamespace(get=Mock(return_value={
            "vendorpayment": {"payment_id": "VP1", "payment_number": "PMT-001", "location_id": "LOC_A", "bills": [{"bill_id": "B1"}]}
        })),
        customer_payments=SimpleNamespace(get=Mock(return_value={
            "payment": {"payment_id": "CP1", "payment_number": "RCVD-001", "location_id": "LOC_B", "invoices": [{"location_id": "LOC_C", "invoice_number": "INV-001"}]}
        })),
        bills=SimpleNamespace(get=Mock(return_value={
            "bill": {"bill_id": "B1", "bill_number": "BILL-001", "location_id": "LOC_A"}
        })),
    )

    res = review_bank_payment_locations(books, "BANK1", (("2025-04-01", "2026-03-31"),))
    assert res["total_entries"] == 2
    assert res["audited_payments"] == 2
    # VP1 matches (LOC_A == LOC_A), CP1 mismatches (LOC_B != LOC_C)
    assert len(res["mismatches"]) == 1
    assert res["mismatches"][0]["transaction_id"] == "CP1"
    assert res["mismatches"][0]["payment_location_id"] == "LOC_B"
    assert res["mismatches"][0]["allocated_invoice_locations"] == {"LOC_C": 1}
