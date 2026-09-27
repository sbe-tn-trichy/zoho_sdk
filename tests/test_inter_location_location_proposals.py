from workflows.inter_location_location_proposals import propose_location_updates


def row(**changes):
    result = {"Date": "01/01/2026", "Financial Year": "FY 2025-26", "Amount": "INR 10.00",
              "Debit Transaction ID": "cp", "Credit Transaction ID": "vp",
              "Credit Type": "Vendor Payment", "Matching Evidence": "Exact reference",
              "Debit Location ID": "a", "Credit Location ID": "b",
              "Debit Location": "Branch A", "Credit Location": "Branch B",
              "Invoice ID": "i", "Invoice Number": "INV", "Invoice Location ID": "b",
              "Invoice Location": "Branch B", "Bill ID": "x", "Bill Number": "BILL",
              "Bill Location ID": "b", "Bill Location": "Branch B"}
    result.update(changes)
    return result


def test_proposes_payment_move_when_all_documents_agree():
    proposal = propose_location_updates([row(), row(**{"Invoice ID": "i2", "Invoice Number": "INV2"})])[0]
    assert proposal["status"] == "proposed"
    assert proposal["invoice_numbers"] == ["INV", "INV2"]
    assert proposal["moves"] == [{"transaction_type": "customer_payment", "transaction_id": "cp",
                                  "from_location_id": "a", "from_location": "Branch A",
                                  "to_location_id": "b", "to_location": "Branch B"}]


def test_conflicting_document_locations_require_review():
    proposal = propose_location_updates([row(**{"Invoice Location ID": "a", "Invoice Location": "Branch A"})])[0]
    assert proposal["status"] == "manual_review"
    assert proposal["moves"] == []


def test_blank_reference_requires_review_even_when_documents_agree():
    proposal = propose_location_updates([row(**{"Matching Evidence": "Verify pairing"})])[0]
    assert proposal["status"] == "manual_review"


def test_missing_bill_requires_review():
    proposal = propose_location_updates([row(**{"Bill ID": "", "Bill Location ID": ""})])[0]
    assert proposal["status"] == "manual_review"


def test_payment_document_rows_are_not_treated_as_contra_proposals():
    assert propose_location_updates([row(**{"Issue Type": "Customer payment vs invoice"})]) == []
