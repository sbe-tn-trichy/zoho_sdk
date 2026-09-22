"""Unit tests for GSTR-2 verification workflow."""

from unittest.mock import MagicMock
from workflows.gstr2_verification.verifier import (
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
