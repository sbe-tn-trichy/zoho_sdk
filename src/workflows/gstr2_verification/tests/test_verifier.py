"""Unit tests for GSTR-2 verification workflow."""

from datetime import date
import re
from unittest.mock import MagicMock
import pytest
from workflows.gstr2_verification.verifier import (
    AggregatePurchaseMapping,
    GSTR2VerificationConfig,
    GSTR2Verifier,
    normalize_doc_number,
    render_markdown_report,
    verify_gstr2,
)


def test_normalize_doc_number():
    assert normalize_doc_number("25-26/IC000092") == "2526IC000092"
    assert normalize_doc_number("CDT2509931869534") == "CDT2509931869534"
    assert normalize_doc_number("000123") == "123"
    assert normalize_doc_number("INV-0045/2025") == "INV00452025"
    assert normalize_doc_number(None) == ""
    assert normalize_doc_number("") == ""


def test_same_vendor_and_amount_do_not_override_different_expense_reference():
    verifier = GSTR2Verifier(MagicMock())
    gstin = "33AAACH2702H1Z7"
    expense = {
        "expense_id": "expense-1", "expense_number": "",
        "reference_number": "EPR2605308968789",
        "norm_number": "", "norm_ref_number": "EPR2605308968789",
        "gst_no": gstin, "vendor_name": "HDFC BANK LIMITED", "total": 236.0,
    }

    wrong_portal_doc = {
        "doc_number": "EPR2603769782832",
        "norm_number": "EPR2603769782832",
        "supplier_gstin": gstin, "supplier_name": "HDFC BANK LIMITED",
        "total_value": 236.0,
    }
    correct_portal_doc = {
        **wrong_portal_doc,
        "doc_number": "EPR2605308968789",
        "norm_number": "EPR2605308968789",
    }

    assert verifier._find_best_match(wrong_portal_doc, [expense], set()) is None
    assert verifier._find_best_match(correct_portal_doc, [expense], set()) is expense


def test_bills_use_transaction_posting_date_for_month_selection():
    books = MagicMock()
    books.bills.list_all.return_value = [
        {"bill_id": "posted-oct", "date": "2025-09-30", "txn_value_date": "2025-10-01", "status": "paid"},
        {"bill_id": "posted-sep", "date": "2025-10-01", "txn_value_date": "2025-09-30", "status": "paid"},
        {"bill_id": "ordinary", "date": "2025-10-02", "status": "paid"},
    ]
    verifier = GSTR2Verifier(books)

    bills = verifier._fetch_books_bills(date(2025, 10, 1), date(2025, 10, 31), [])

    books.bills.list_all.assert_called_once_with()
    assert {bill["bill_id"] for bill in bills} == {"posted-oct", "ordinary"}
    assert next(bill for bill in bills if bill["bill_id"] == "posted-oct")["posting_date"] == "2025-10-01"


def test_books_documents_are_scoped_by_location_registration_not_vendor_gstin():
    books = MagicMock()
    books.bills.list_all.return_value = [
        {"bill_id": "bill-target", "bill_number": "IN-SCOPE", "date": "2025-10-31",
         "location_id": "loc-target", "gst_no": "29AAACO0160A1Z3",
         "vendor_name": "LEDVANCE", "total": 100.0, "status": "paid"},
        {"bill_id": "bill-other", "bill_number": "OUT-OF-SCOPE", "date": "2025-10-31",
         "location_id": "loc-other", "gst_no": "29AAACO0160A1Z3",
         "vendor_name": "LEDVANCE", "total": 200.0, "status": "paid"},
    ]
    books.bills.get.return_value = {"bill": {"tax_total": 0.0}}
    books.expenses.list_all.return_value = [
        {"expense_id": "expense-other", "date": "2025-10-31",
         "location_id": "loc-other", "tax_amount": 18.0, "total": 118.0},
    ]
    books.vendor_credits.list_all.return_value = [
        {"vendor_credit_id": "credit-other", "date": "2025-10-31",
         "location_id": "loc-other", "total": 50.0, "status": "open"},
    ]
    portal = {"data": {"rtnprd": "102025", "gstin": "33AATFB2164K1Z9",
                       "docdata": {"b2b": [], "cdnr": []}}}

    config = GSTR2VerificationConfig(location_gstin_map={
        "33AATFB2164K1Z9": ["loc-target"],
        "33AFSFS0069L1ZH": ["loc-other"],
    })
    result = GSTR2Verifier(books, config).run(portal)
    summary = result["reconciliation"]["summary"]
    assert result["fetch_errors"] == []
    assert summary["books_total_bills_count"] == 1
    assert summary["books_total_expenses_count"] == 0
    assert summary["books_total_credits_count"] == 0
    assert result["metadata"]["included_locations"] == [
        {"location_id": "loc-target"},
    ]
    books.locations.list_all.assert_not_called()


def test_unknown_books_location_is_reported_as_incomplete():
    books = MagicMock()
    books.bills.list_all.return_value = [
        {"bill_id": "bill-unknown", "bill_number": "UNKNOWN", "date": "2025-10-31",
         "location_id": "loc-unknown", "total": 100.0, "status": "paid"},
    ]
    books.bills.get.return_value = {"bill": {"tax_total": 0.0}}
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    portal = {"data": {"rtnprd": "102025", "gstin": "33AATFB2164K1Z9",
                       "docdata": {"b2b": [], "cdnr": []}}}

    config = GSTR2VerificationConfig(location_gstin_map={
        "33AATFB2164K1Z9": ["loc-target"],
    })
    result = GSTR2Verifier(books, config).run(portal)
    assert any(error["source"] == "locations" for error in result["fetch_errors"])


def test_empty_static_location_map_marks_run_incomplete():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    portal = {"data": {"rtnprd": "102025", "gstin": "33AATFB2164K1Z9",
                       "docdata": {"b2b": [], "cdnr": []}}}

    result = GSTR2Verifier(books).run(portal)

    assert {error["error"] for error in result["fetch_errors"]} == {
        "GSTR2_LOCATION_GSTIN_MAP is empty",
    }
    books.locations.list_all.assert_not_called()


def test_location_map_rejects_scalar_location_list():
    verifier = GSTR2Verifier(
        MagicMock(),
        GSTR2VerificationConfig(location_gstin_map={
            "33AATFB2164K1Z9": "loc-target",
        }),
    )
    errors = []

    assert verifier._configured_location_gstins(errors) == {}
    assert errors == [{
        "source": "locations",
        "error": "Invalid static location mapping for GSTIN '33AATFB2164K1Z9'",
    }]


def test_location_map_rejects_location_assigned_to_multiple_gstins():
    verifier = GSTR2Verifier(
        MagicMock(),
        GSTR2VerificationConfig(location_gstin_map={
            "33AATFB2164K1Z9": ["loc-shared"],
            "33AFSFS0069L1ZH": ["loc-shared"],
        }),
    )
    errors = []

    locations = verifier._configured_location_gstins(errors)

    assert locations["loc-shared"]["gstin"] == "33AATFB2164K1Z9"
    assert errors == [{
        "source": "locations",
        "error": "Location loc-shared is mapped to multiple GSTINs",
    }]


@pytest.mark.parametrize(
    ("discount_type", "before_tax", "expected"),
    [
        ("entity_level", True, 2448.0),
        ("entity_level", False, 2880.0),
        ("item_level", True, 2880.0),
    ],
)
def test_books_net_taxable_respects_discount_timing(discount_type, before_tax, expected):
    document = {
        "sub_total": 2880.0,
        "discount_type": discount_type,
        "is_discount_before_tax": before_tax,
        "discount_total": 432.0,
        "discount_amount": 432.0,
    }
    assert GSTR2Verifier._books_net_taxable(document) == expected


def test_books_net_taxable_falls_back_to_discount_amount():
    assert GSTR2Verifier._books_net_taxable({
        "sub_total": 2880.0,
        "discount_type": "entity_level",
        "is_discount_before_tax": True,
        "discount_amount": 432.0,
    }) == 2448.0
    assert GSTR2Verifier._books_net_taxable({}) is None


@pytest.mark.parametrize("changed_amount", [False, True])
@pytest.mark.parametrize("portal_doc_type", ["invoice", "debit_note"])
def test_aggregate_purchase_mapping_requires_exact_count_and_components(
    changed_amount, portal_doc_type,
):
    books = MagicMock()
    books.bills.list_all.return_value = [{
        "bill_id": "bill-1", "bill_number": "DN_SEP", "date": "2025-09-29",
        "vendor_name": "POLYCAB", "gst_no": "33AAACP6474E1ZK",
        "total": 354.0, "status": "paid",
    }]
    books.bills.get.return_value = {"bill": {
        "sub_total": 300.0, "tax_total": 54.0,
    }}
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    second_total = 237.0 if changed_amount else 236.0
    suppliers = [
        {"ctin": "33AAACP6474E1ZK", "trdnm": "POLYCAB", "inv": [{
            "inum": "TN/ARD1", "dt": "29-09-2025", "val": 118.0,
            "txval": 100.0, "igst": 18.0,
        }]},
        {"ctin": "29AAACP6474E1Z9", "trdnm": "POLYCAB", "inv": [{
            "inum": "KA/ARD2", "dt": "29-09-2025", "val": second_total,
            "txval": 200.0, "igst": 36.0,
        }]},
    ]
    if portal_doc_type == "debit_note":
        for supplier in suppliers:
            supplier["nt"] = [{
                **{k: v for k, v in invoice.items() if k not in {"inum", "dt"}},
                "ntnum": invoice["inum"], "dt": invoice["dt"], "typ": "D",
            } for invoice in supplier.pop("inv")]
    portal = {"data": {"rtnprd": "092025", "docdata": {
        "b2b": suppliers if portal_doc_type == "invoice" else [],
        "cdnr": suppliers if portal_doc_type == "debit_note" else [],
    }}}
    mapping = AggregatePurchaseMapping(
        month="2025-09", bill_id="bill-1", bill_number="DN_SEP",
        portal_doc_type=portal_doc_type,
        portal_doc_date="2025-09-29", portal_doc_number_pattern=r"(?:TN|KA)/ARD[0-9]+",
        supplier_gstins=("33AAACP6474E1ZK", "29AAACP6474E1Z9"),
        expected_count=2, expected_taxable=300.0, expected_tax=54.0,
        expected_total=354.0,
    )
    result = GSTR2Verifier(books, GSTR2VerificationConfig(
        aggregate_mappings=(mapping,),
    )).run(portal)
    rec = result["reconciliation"]
    report = render_markdown_report(result)
    assert re.search(r"\*\*Last Run:\*\* \d{2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} [AP]M IST", report)
    if changed_amount:
        assert rec["aggregate_matches"] == []
        assert rec["summary"]["missing_in_books_count"] == 2
        assert rec["summary"]["missing_in_gstr2_bills_count"] == 1
        assert rec["aggregate_warnings"]
    else:
        assert rec["summary"]["matched_count"] == 2
        assert rec["summary"]["matched_books_count"] == 1
        assert rec["summary"]["missing_in_books_count"] == 0
        assert rec["summary"]["missing_in_gstr2_bills_count"] == 0
        assert len(rec["aggregate_matches"]) == 1
        assert "| `DN_SEP` | 2 |" in report
        assert "`TN/ARD1`" not in report
        assert "`KA/ARD2`" not in report


def test_value_mismatch_report_shows_both_taxable_and_tax_amounts():
    books = MagicMock()
    books.bills.list_all.return_value = [{
        "bill_id": "bill-1", "bill_number": "INV-1", "date": "2025-05-24",
        "vendor_name": "SUPPLIER", "gst_no": "33AAAAA0000A1Z5",
        "total": 125.0, "status": "open",
    }]
    books.bills.get.return_value = {"bill": {"sub_total": 105.0, "tax_total": 20.0}}
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    portal = {"data": {"rtnprd": "052025", "docdata": {"b2b": [{
        "ctin": "33AAAAA0000A1Z5", "trdnm": "SUPPLIER", "inv": [{
            "inum": "INV-1", "dt": "24-05-2025", "val": 118.0,
            "txval": 100.0, "igst": 18.0, "itcavl": "Y",
        }],
    }], "cdnr": []}}}

    result = GSTR2Verifier(books).run(portal)
    mismatch = result["reconciliation"]["value_mismatches"][0]
    assert (mismatch["gstr2_taxable"], mismatch["books_taxable"]) == (100.0, 105.0)
    assert (mismatch["gstr2_tax"], mismatch["books_tax"]) == (18.0, 20.0)
    report = render_markdown_report(result)
    assert "| 2B Taxable | Books Taxable | 2B Tax | Books Tax |" in report
    assert "₹100.00 | ₹105.00 | ₹18.00 | ₹20.00 | ₹118.00 | ₹125.00" in report


def test_value_mismatch_uses_net_taxable_after_pre_tax_discount():
    books = MagicMock()
    books.bills.list_all.return_value = [{
        "bill_id": "bill-1", "bill_number": "INV-1", "date": "2025-05-24",
        "vendor_name": "SUPPLIER", "gst_no": "33AAAAA0000A1Z5",
        "total": 2888.64, "status": "open",
    }]
    books.bills.get.return_value = {"bill": {
        "sub_total": 2880.0, "discount_type": "entity_level",
        "is_discount_before_tax": True, "discount_total": 432.0,
        "tax_total": 440.64,
    }}
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    portal = {"data": {"rtnprd": "052025", "docdata": {"b2b": [{
        "ctin": "33AAAAA0000A1Z5", "trdnm": "SUPPLIER", "inv": [{
            "inum": "INV-1", "dt": "24-05-2025", "val": 2891.0,
            "txval": 2450.0, "igst": 441.0, "itcavl": "Y",
        }],
    }], "cdnr": []}}}

    result = GSTR2Verifier(books).run(portal)
    mismatch = result["reconciliation"]["value_mismatches"][0]
    assert mismatch["books_taxable"] == 2448.0
    assert "₹2,450.00 | ₹2,448.00 | ₹441.00 | ₹440.64" in render_markdown_report(result)


def test_value_mismatch_report_marks_unavailable_books_components():
    books = MagicMock()
    books.bills.list_all.return_value = [{
        "bill_id": "bill-1", "bill_number": "INV-1", "date": "2025-05-24",
        "vendor_name": "SUPPLIER", "gst_no": "33AAAAA0000A1Z5",
        "total": 125.0, "status": "open",
    }]
    books.bills.get.side_effect = RuntimeError("detail unavailable")
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    portal = {"data": {"rtnprd": "052025", "docdata": {"b2b": [{
        "ctin": "33AAAAA0000A1Z5", "trdnm": "SUPPLIER", "inv": [{
            "inum": "INV-1", "dt": "24-05-2025", "val": 118.0,
            "txval": 100.0, "igst": 18.0, "itcavl": "Y",
        }],
    }], "cdnr": []}}}

    result = GSTR2Verifier(books).run(portal)
    mismatch = result["reconciliation"]["value_mismatches"][0]
    assert mismatch["books_taxable"] is None
    assert mismatch["books_tax"] is None
    assert "₹100.00 | — | ₹18.00 | — |" in render_markdown_report(result)


def test_vendor_credit_mismatch_reads_tax_from_taxes_list():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = [{
        "vendor_credit_id": "credit-1", "vendor_credit_number": "CN-1",
        "date": "2025-05-24", "vendor_name": "SUPPLIER",
        "gst_no": "33AAAAA0000A1Z5", "total": 125.0, "status": "open",
    }]
    books.vendor_credits.get.return_value = {"vendor_credit": {
        "sub_total": 105.0, "taxes": [{"tax_amount": 10.0}, {"tax_amount": 10.0}],
    }}
    portal = {"data": {"rtnprd": "052025", "docdata": {"b2b": [], "cdnr": [{
        "ctin": "33AAAAA0000A1Z5", "trdnm": "SUPPLIER", "nt": [{
            "nt_num": "CN-1", "nt_dt": "24-05-2025", "val": 118.0,
            "txval": 100.0, "igst": 18.0, "itcavl": "Y",
        }],
    }]}}}

    result = GSTR2Verifier(books).run(portal)
    mismatch = result["reconciliation"]["value_mismatches"][0]
    assert mismatch["books_tax"] == 20.0


def test_period_vendor_credits_use_books_response_key():
    books = MagicMock()
    credit = {
        "vendor_credit_id": "credit-1",
        "vendor_credit_number": "3902255964",
        "reference_number": "24656952",
        "date": "2025-04-21",
        "vendor_name": "CARL ZEISS INDIA (BANGALORE) PVT LTD",
        "gst_no": "29AADCC6152H1ZM",
        "total": 1850.24,
        "status": "closed",
    }
    books.vendor_credits.list_all.side_effect = (
        lambda *, params, resource_key: [credit]
        if resource_key == "vendor_credits" else []
    )

    errors = []
    credits = GSTR2Verifier(books)._fetch_books_vendor_credits(
        date(2025, 4, 1), date(2025, 4, 30), errors
    )

    assert errors == []
    assert len(credits) == 1
    assert credits[0]["credit_number"] == "3902255964"
    assert credits[0]["total"] == 1850.24


def test_gstr2_verifier_reconciliation():
    mock_books = MagicMock()
    mock_books.bills.list_all.return_value = [
        {
            "bill_id": "bill_1",
            "bill_number": "CDT2509931869534",
            "reference_number": "",
            "date": "2025-04-30",
            "vendor_name": "HDFC BANK LIMITED",
            "gst_no": "33AAACH2702H1Z7",
            "total": 236.0,
            "status": "paid",
        },
        {
            "bill_id": "bill_2",
            "bill_number": "25-26/IC000092",
            "reference_number": "IC000092",
            "date": "2025-04-24",
            "vendor_name": "AMBAL PAPER MART",
            "gst_no": "33AAPFA1053L1ZI",
            "total": 350.0,
            "status": "paid",
        },
        {
            "bill_id": "bill_3",
            "bill_number": "BOOK_ONLY_001",
            "reference_number": "",
            "date": "2025-04-15",
            "vendor_name": "SUPPLIER NOT FILED",
            "gst_no": "33AAAAA0000A1Z5",
            "total": 5000.0,
            "status": "open",
        },
    ]
    mock_books.vendor_credits.list_all.return_value = []

    sample_gstr2_data = {
        "data": {
            "gstin": "33AATFB2164K1Z9",
            "rtnprd": "042025",
            "gendt": "15-05-2025",
            "docdata": {
                "b2b": [
                    {
                        "ctin": "33AAACH2702H1Z7",
                        "trdnm": "HDFC BANK LIMITED",
                        "inv": [
                            {
                                "inum": "CDT2509931869534",
                                "dt": "30-04-2025",
                                "val": 236.0,
                                "txval": 200.0,
                                "cgst": 18.0,
                                "sgst": 18.0,
                                "igst": 0.0,
                                "cess": 0.0,
                                "rev": "N",
                                "itcavl": "Y",
                            }
                        ],
                    },
                    {
                        "ctin": "33AAPFA1053L1ZI",
                        "trdnm": "AMBAL PAPER MART",
                        "inv": [
                            {
                                "inum": "25-26/IC000092",
                                "dt": "24-04-2025",
                                "val": 350.0,
                                "txval": 296.61,
                                "cgst": 26.69,
                                "sgst": 26.69,
                                "igst": 0.0,
                                "cess": 0.0,
                                "rev": "N",
                                "itcavl": "Y",
                            }
                        ],
                    },
                    {
                        "ctin": "33BRXPS8956C1Z0",
                        "trdnm": "MAHARAJA TRADERS",
                        "inv": [
                            {
                                "inum": "CR0187/2025-26",
                                "dt": "30-04-2025",
                                "val": 1499.0,
                                "txval": 1270.36,
                                "cgst": 114.33,
                                "sgst": 114.33,
                                "igst": 0.0,
                                "cess": 0.0,
                                "rev": "N",
                                "itcavl": "Y",
                            }
                        ],
                    },
                ],
                "cdnr": [],
            },
        }
    }

    verifier = GSTR2Verifier(mock_books)
    result = verifier.run(sample_gstr2_data)

    rec = result["reconciliation"]
    summary = rec["summary"]

    assert summary["gstr2_total_docs"] == 3
    assert summary["matched_count"] == 2
    assert summary["missing_in_books_count"] == 1
    assert summary["missing_in_gstr2_bills_count"] == 1

    # Verify missing in books document
    missing_b = rec["missing_in_books"][0]
    assert missing_b["doc_number"] == "CR0187/2025-26"
    assert missing_b["supplier_name"] == "MAHARAJA TRADERS"

    # Verify missing in GSTR-2B bill (ITC at risk)
    missing_g = rec["missing_in_gstr2_bills"][0]
    assert missing_g["bill_number"] == "BOOK_ONLY_001"
    assert missing_g["total"] == 5000.0

    # Test report rendering
    report = render_markdown_report(result)
    assert "# GSTR-2B vs Zoho Books Reconciliation Report (2025-04)" in report
    assert "HDFC BANK LIMITED" in report
    assert "CR0187/2025-26" in report
    assert "BOOK_ONLY_001" in report


def test_gst_expense_is_matched_and_zero_tax_expense_is_excluded():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    books.expenses.list_all.return_value = [
        {
            "expense_id": "expense-1",
            "reference_number": "BANK/GST/101",
            "date": "2025-04-10",
            "vendor_name": "GST BANK",
            "gst_no": "33AAACH2702H1Z7",
            "sub_total": 100.0,
            "tax_amount": 18.0,
            "total": 118.0,
            "status": "unbilled",
        },
        {
            "expense_id": "expense-2",
            "reference_number": "NO-GST-1",
            "date": "2025-04-11",
            "tax_amount": 0.0,
            "total": 50.0,
            "status": "unbilled",
        },
    ]
    portal = {
        "data": {
            "gstin": "33AATFB2164K1Z9",
            "rtnprd": "042025",
            "docdata": {
                "b2b": [{
                    "ctin": "33AAACH2702H1Z7",
                    "trdnm": "GST BANK",
                    "inv": [{
                        "inum": "BANK-GST-101",
                        "dt": "10-04-2025",
                        "val": 118.0,
                        "txval": 100.0,
                        "igst": 18.0,
                        "itcavl": "Y",
                    }],
                }],
                "cdnr": [],
            },
        },
    }

    result = GSTR2Verifier(books).run(portal)

    summary = result["reconciliation"]["summary"]
    assert summary["books_total_expenses_count"] == 1
    assert summary["matched_count"] == 1
    assert summary["missing_in_gstr2_expenses_count"] == 0
    assert result["reconciliation"]["matched_documents"][0]["books_doc"]["doc_type"] == "expense"
    books.expenses.get.assert_not_called()


def test_reverse_charge_expense_matches_rcm_portal_invoice():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    books.expenses.list_all.return_value = [{
        "expense_id": "vrl-1", "reference_number": "1092213251",
        "date": "2025-09-27", "vendor_name": "VRL LOGISTICS LIMITED",
        "gst_no": "33AABCV3609C1ZU", "sub_total": 810.0,
        "total": 810.0, "total_without_tax": 810.0,
        "status": "nonbillable",
    }]
    books.expenses.get.return_value = {"expense": {
        "expense_id": "vrl-1", "reference_number": "1092213251",
        "date": "2025-09-27", "vendor_name": "VRL LOGISTICS LIMITED",
        "gst_no": "33AABCV3609C1ZU", "sub_total": 810.0,
        "tax_amount": 0.0, "reverse_charge_tax_amount": 40.5,
        "total": 810.0, "status": "nonbillable",
    }}
    portal = {"data": {"rtnprd": "092025", "docdata": {"b2b": [{
        "ctin": "33AABCV3609C1ZU", "trdnm": "VRL LOGISTICS LIMITED",
        "inv": [{"inum": "1092213251", "dt": "27-09-2025", "val": 810.0,
                 "txval": 810.0, "cgst": 20.25, "sgst": 20.25,
                 "rev": "Y", "itcavl": "Y"}],
    }], "cdnr": []}}}

    rec = GSTR2Verifier(books).run(portal)["reconciliation"]

    assert rec["summary"]["matched_count"] == 1
    assert rec["summary"]["missing_in_books_count"] == 0
    assert rec["summary"]["missing_in_gstr2_expenses_count"] == 0
    assert rec["matched_documents"][0]["books_tax"] == 40.5
    assert rec["matched_documents"][0]["books_doc"]["reverse_charge"] is True


def test_reverse_charge_expense_does_not_match_forward_tax_invoice():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    books.expenses.list_all.return_value = [{
        "expense_id": "rcm-1", "reference_number": "INV-1",
        "date": "2025-09-27", "gst_no": "33AABCV3609C1ZU", "total": 810.0,
        "tax_amount": 0.0, "reverse_charge_tax_amount": 40.5,
    }]
    portal = {"data": {"rtnprd": "092025", "docdata": {"b2b": [{
        "ctin": "33AABCV3609C1ZU", "inv": [{"inum": "INV-1", "dt": "27-09-2025",
        "val": 810.0, "txval": 810.0, "cgst": 20.25, "sgst": 20.25,
        "rev": "N", "itcavl": "Y"}],
    }], "cdnr": []}}}

    rec = GSTR2Verifier(books).run(portal)["reconciliation"]

    assert rec["summary"]["matched_count"] == 0
    assert rec["summary"]["missing_in_books_count"] == 1
    assert rec["summary"]["missing_in_gstr2_expenses_count"] == 0


def test_unmatched_itemized_gst_expense_is_loaded_and_reported():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.vendor_credits.list_all.return_value = []
    books.expenses.list_all.return_value = [{
        "expense_id": "expense-3",
        "reference_number": "EXP-003",
        "date": "2025-04-12",
        "vendor_name": "SERVICE VENDOR",
        "gst_no": "33AAAAA0000A1Z5",
        "total": 236.0,
        "status": "unbilled",
        "is_itemized_expense": True,
    }]
    books.expenses.get.return_value = {
        "expense": {
            "expense_id": "expense-3",
            "reference_number": "EXP-003",
            "date": "2025-04-12",
            "vendor_name": "SERVICE VENDOR",
            "gst_no": "33AAAAA0000A1Z5",
            "total": 236.0,
            "status": "unbilled",
            "line_items": [{"amount": 200.0, "tax_amount": 36.0}],
        }
    }
    portal = {
        "data": {
            "gstin": "33AATFB2164K1Z9",
            "rtnprd": "042025",
            "docdata": {"b2b": [], "cdnr": []},
        }
    }

    result = GSTR2Verifier(books).run(portal)

    rec = result["reconciliation"]
    assert rec["summary"]["missing_in_gstr2_expenses_count"] == 1
    assert rec["missing_in_gstr2_expenses"][0]["tax_total"] == 36.0
    assert "GST Expenses Missing in GSTR-2B" in render_markdown_report(result)
    books.expenses.get.assert_called_once_with("expense-3")


def test_commercial_zero_tax_vendor_credit_is_classified_as_zero_tax():
    books = MagicMock()
    books.bills.list_all.return_value = []
    books.expenses.list_all.return_value = []
    books.vendor_credits.list_all.return_value = [
        {
            "vendor_credit_id": "vc-comm-1",
            "vendor_credit_number": "20256600750",
            "date": "2025-04-28",
            "vendor_name": "BAUSCH & LOMB INDIA PRIVATE LTD",
            "gst_no": "",
            "total": 7410.0,
            "tax_total": 0.0,
            "status": "closed",
        },
        {
            "vendor_credit_id": "vc-gst-1",
            "vendor_credit_number": "GST-CN-100",
            "date": "2025-04-28",
            "vendor_name": "GST VENDOR",
            "gst_no": "33AAAAA0000A1Z5",
            "total": 1180.0,
            "tax_total": 180.0,
            "status": "open",
        }
    ]
    portal = {
        "data": {
            "gstin": "33AATFB2164K1Z9",
            "rtnprd": "042025",
            "docdata": {"b2b": [], "cdnr": []},
        }
    }

    result = GSTR2Verifier(books).run(portal)
    rec = result["reconciliation"]

    # Only GST vendor credit should be in missing_in_gstr2_credits
    assert len(rec["missing_in_gstr2_credits"]) == 1
    assert rec["missing_in_gstr2_credits"][0]["credit_number"] == "GST-CN-100"

    # Commercial credit note should be in zero_tax_bills (no tax component)
    zero_tax = rec["zero_tax_bills"]
    assert any(
        z.get("credit_number") == "20256600750"
        and "commercial / non-GST credit" in z.get("reason", "")
        for z in zero_tax
    )

