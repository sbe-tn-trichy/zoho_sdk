"""Fiscal-year timing reconciliation of monthly result records."""

from copy import deepcopy

from workflows.gstr2_verification import (
    fiscal_months, reconcile_fiscal_year, render_fiscal_year_missing_details,
)


def _result(month, portal=(), bills=()):
    return {"metadata": {"target_month": month}, "reconciliation": {
        "missing_in_books": list(portal), "missing_in_gstr2_bills": list(bills),
        "missing_in_gstr2_expenses": [], "missing_in_gstr2_credits": [],
        "matched_documents": [], "aggregate_matches": [], "vendor_summaries": [],
        "summary": {"matched_count": 0, "matched_tax": 0,
                    "missing_in_books_count": len(portal),
                    "missing_in_gstr2_bills_count": len(bills)},
    }}


PORTAL = {"doc_number": "INV-01", "norm_number": "INV01", "doc_type": "invoice",
          "supplier_gstin": "33AAA", "reverse_charge": False, "total_value": 118.0,
          "tax_total": 18.0, "taxable_value": 100.0}
BOOKS = {"bill_id": "1", "bill_number": "INV-01", "reference_number": "",
         "gst_no": "33AAA", "total": 118.0, "tax_total": 18.0,
         "sub_total": 100.0}


def test_fiscal_months_april_to_march():
    assert fiscal_months(2025) == tuple(
        [f"2025-{month:02d}" for month in range(4, 13)] +
        [f"2026-{month:02d}" for month in range(1, 4)])


def test_cross_month_match_removes_both_false_gaps():
    june = _result("2025-06", bills=[deepcopy(BOOKS)])
    july = _result("2025-07", portal=[deepcopy(PORTAL)])
    matches = reconcile_fiscal_year([june, july], tolerance=1)
    assert len(matches) == 1
    assert matches[0]["books_month"] == "2025-06"
    assert matches[0]["portal_month"] == "2025-07"
    assert june["reconciliation"]["summary"]["missing_in_gstr2_bills_count"] == 0
    assert july["reconciliation"]["summary"]["missing_in_books_count"] == 0
    assert july["reconciliation"]["summary"]["matched_count"] == 1


def test_ambiguous_or_mismatched_documents_remain_open():
    june = _result("2025-06", bills=[deepcopy(BOOKS), {**BOOKS, "bill_id": "2"}])
    july = _result("2025-07", portal=[deepcopy(PORTAL)])
    assert reconcile_fiscal_year([june, july], tolerance=1) == []
    june = _result("2025-06", bills=[{**BOOKS, "tax_total": 22.0}])
    july = _result("2025-07", portal=[deepcopy(PORTAL)])
    assert reconcile_fiscal_year([june, july], tolerance=1) == []


def test_fiscal_details_show_only_unresolved_documents_and_actions():
    june = _result("2025-06", bills=[deepcopy(BOOKS)])
    july = _result("2025-07", portal=[deepcopy(PORTAL)])
    july["reconciliation"]["missing_in_books"].append({
        **PORTAL, "doc_number": "PORTAL-ONLY", "norm_number": "PORTALONLY",
        "supplier_name": "Supplier | Name", "doc_date": "2025-07-10",
    })
    june["reconciliation"]["missing_in_gstr2_expenses"].append({
        "expense_id": "e1", "expense_number": "EXP-1", "reference_number": "REF-1",
        "vendor_name": "Vendor", "gst_no": "33AAA", "date": "2025-06-10",
        "sub_total": 100, "tax_total": 18, "total": 118,
    })
    july["reconciliation"]["missing_in_books"].append({
        **PORTAL, "doc_number": "GSTIN-DIFF", "norm_number": "GSTINDIFF",
        "supplier_gstin": "27AAA", "taxable_value": 100, "tax_total": 18,
    })
    june["reconciliation"]["missing_in_gstr2_bills"].append({
        **BOOKS, "bill_id": "gstin-diff", "bill_number": "GSTIN-DIFF",
        "gst_no": "06AAA", "sub_total": 100, "tax_total": 18,
    })
    june["reconciliation"]["value_mismatches"] = [{
        "gstr2_doc": {**PORTAL, "doc_number": "DIFF-1", "doc_date": "2025-06-11"},
        "books_doc": {"bill_number": "DIFF-1"},
        "gstr2_taxable": 100, "books_taxable": None,
        "gstr2_tax": 18, "books_tax": None,
        "gstr2_amount": 118, "books_amount": 120, "diff": 2,
    }]
    reconcile_fiscal_year([june, july], tolerance=1)

    report = "\n".join(render_fiscal_year_missing_details([june, july]))
    assert "In GSTR-2B, missing in Books (1)" in report
    assert "Supplier \\| Name" in report
    assert "PORTAL-ONLY" in report
    assert "Supplier review summary" in report
    assert "Check for an unrecorded purchase" in report
    assert "In Books, missing in GSTR-2B (1)" in report
    assert "Possible counterparts with different GSTINs (1)" in report
    assert "GSTIN-DIFF | 2025-07 | 2025-06 | 27AAA | 06AAA" in report
    assert report.count("GSTIN-DIFF") == 1
    assert "EXP-1 | REF-1" in report
    assert "Value mismatches (1)" in report
    assert "DIFF-1" in report
    assert "₹100.00 | — | ₹18.00 | —" in report
    assert "INV-01" not in report
