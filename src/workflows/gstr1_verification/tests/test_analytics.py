from unittest.mock import MagicMock

import pytest

from workflows.gstr1_verification import GSTR1VerificationConfig, GSTR1Verifier, verify_gstr1


def clients(rows=None):
    books, analytics = MagicMock(), MagicMock()
    analytics.queries.execute.side_effect = [
        [{"Location ID": "L1", "Location Name": "Branch", "GSTIN": "GST1"}],
        rows or [], [],
    ]
    return books, analytics


def invoice(day="2026-07-01", status="Sent", **extra):
    return {"Invoice ID": "I1", "Invoice Number": "INV-001", "Invoice Date": day,
            "Invoice Status": status, "Location ID": "L1", "Total (BCY)": 100,
            **extra}


def test_default_uses_analytics_and_filters_month_from_fy():
    books, analytics = clients([invoice(), invoice("2026-06-30")])
    report = verify_gstr1(books, month="2026-07", analytics_client=analytics,
                         config=GSTR1VerificationConfig(e_invoice_applicable=False))
    assert report["data_source"] == "analytics"
    assert report["complete"]
    assert report["invoices"]["count"] == 1
    assert "GST1" in report["gst_registrations"]
    assert analytics.queries.execute.call_count == 3
    sql = analytics.queries.execute.call_args_list[1].args[1]
    assert "2026-04-01" in sql and "2027-03-31" in sql
    assert books.mock_calls == []


def test_force_refresh_does_not_call_analytics():
    books, analytics = clients()
    books.locations.list_all.return_value = []
    books.invoices.list_all.return_value = []
    books.credit_notes.list_all.return_value = []
    report = GSTR1Verifier(books, analytics_client=analytics).run(month="2026-07", force_refresh=True)
    assert report["data_source"] == "books"
    assert books.invoices.list_all.call_count == 2
    assert analytics.mock_calls == []


@pytest.mark.parametrize("extra,passed", [({}, False),
    ({"E-Invoice Status": "Pushed", "IRN": "reference"}, True),
    ({"E-Invoice Status": "Pushed"}, False),
    ({"E-Invoice Status": "Not Applicable"}, True)])
def test_einvoice_evidence(extra, passed):
    _, analytics = clients([invoice(**extra)])
    report = verify_gstr1(month="2026-07", analytics_client=analytics)
    assert report["checks"]["einvoice_push"]["passed"] is passed


@pytest.mark.parametrize("rows", [[invoice(day="bad")], [invoice(status="")]])
def test_invalid_export_is_incomplete(rows):
    books, analytics = clients(rows)
    report = verify_gstr1(books, month="2026-07", analytics_client=analytics)
    assert not report["complete"] and not report["overall_passed"]
    assert report["fetch_errors"][0]["source"] == "analytics_invoices"
    assert books.mock_calls == []


def test_analytics_failure_never_falls_back_to_books():
    books, analytics = clients()
    analytics.queries.execute.side_effect = RuntimeError("export failed")
    report = verify_gstr1(books, month="2026-07", analytics_client=analytics)
    assert not report["complete"]
    assert len(report["fetch_errors"]) == 3
    assert books.mock_calls == []


def test_credit_notes_and_drafts_are_normalized():
    _, analytics = clients()
    analytics.queries.execute.side_effect = [[], [], [{
        "Credit Note ID": "C1", "Credit Note Number": "CN-001",
        "Credit Note Date": "2026-07-01", "Credit Note Status": "Draft",
    }]]
    report = verify_gstr1(month="2026-07", analytics_client=analytics)
    assert report["credit_notes"]["count"] == 1
    assert report["checks"]["draft_documents"]["count"] == 1


def test_selected_client_is_required():
    with pytest.raises(ValueError, match="Analytics client"):
        verify_gstr1(MagicMock(), month="2026-07")
    with pytest.raises(ValueError, match="Books client"):
        verify_gstr1(month="2026-07", force_refresh=True)


def test_synced_books_column_names():
    _, analytics = clients([invoice(**{
        "e-Invoice Status.": "Pushed", "e-Invoice Reference Number.": "invoice-irn"})])
    analytics.queries.execute.side_effect = [[], [invoice(**{
        "e-Invoice Status.": "Pushed", "e-Invoice Reference Number.": "invoice-irn"})], [{
        "CreditNotes ID": "C1", "Credit Note Number": "CN-001",
        "Credit Note Date": "01/07/2026", "Credit Note Status": "Closed",
        "e-Invoice Status.": "Pushed", "e-Invoice Reference Number.": "credit-irn",
    }]]
    report = verify_gstr1(month="2026-07", analytics_client=analytics,
                         config=GSTR1VerificationConfig(validate_credit_note_hsn=False))
    assert report["complete"]
    assert report["credit_notes"]["count"] == 1
    check = report["checks"]["einvoice_push"]
    assert check["passed"] and len(check["pushed"]) == 2
