from datetime import date
from unittest.mock import MagicMock

import pytest

from workflows.gstr1_verification import GSTR1VerificationConfig, render_markdown_report, verify_gstr1
from workflows.gstr1_verification.hsn import _normalize, _six_months_before, check_credit_note_hsn


MAP = {"L1": "GST1", "L2": "GST2", "L3": "GST1"}
DOC = {"creditnote_id": "CN1", "creditnote_number": "CN-001", "date": "2026-09-10",
       "status": "open", "location_id": "L1", "customer_id": "CUSTOMER1",
       "total_taxable_amount": 100, "taxes": [], "tax_total": 0, "total": 100}


def line(hsn="8504", **values):
    return _normalize({"document_id": "CN1", "document_number": "CN-001", "date": "2026-09-10",
        "status": "open", "location_id": "L1", "customer_id": "CUSTOMER1", "customer_name": "Customer",
        "line_id": "LINE1", "hsn": hsn, "gst_treatment": "Registered Business - Regular", **values})


def check(invoices, credits=None, **kwargs):
    return check_credit_note_hsn([DOC], credits if credits is not None else [line()], invoices, MAP,
                                evidence_complete=True, **kwargs)


def test_prior_year_invoice_for_same_customer_matches_and_numeric_hsn_normalizes():
    result = check([line(8504.0, document_id="INV1", date="2025-03-01")])
    assert result["passed"] and result["checked_lines"] == 1


@pytest.mark.parametrize("overrides", [
    {"customer_id": "OTHER"}, {"location_id": "L2"}, {"date": "2026-09-11"},
    {"status": "void"}, {"status": "draft"}, {"hsn": "850440"},
])
def test_other_customer_gstin_future_void_draft_or_different_hsn_does_not_match(overrides):
    result = check([line(document_id="INV1", **overrides)])
    assert not result["passed"] and result["complete"]
    assert result["violations"][0]["hsn"] == "8504"


def test_same_registration_other_location_and_same_day_invoice_matches():
    assert check([line(location_id="L3", document_id="INV1")])["passed"]


def test_violation_lists_available_invoice_hsns_and_customer_identity():
    result = check([line("8414", document_id="INV1")])
    finding = result["violations"][0]
    assert finding["invoice_hsns"] == ["8414"]
    assert finding["customer_id"] == "CUSTOMER1" and finding["credit_note_number"] == "CN-001"


@pytest.mark.parametrize("values", [{"hsn": ""}, {"customer_id": ""}, {"line_id": ""},
                                     {"location_id": ""}, {"date": "2026-09-09"}, {"status": "void"}])
def test_missing_or_conflicting_credit_evidence_is_incomplete(values):
    result = check([], [line(**values)])
    assert not result["passed"] and not result["complete"]
    assert result["unverifiable"] and not result["violations"]


def test_unsynced_credit_note_and_unknown_invoice_hsn_are_incomplete():
    assert not check([], [])["complete"]
    assert not check([line("", document_id="INV1")])["complete"]
    assert not check([line(document_id="INV1", location_id="UNKNOWN")])["complete"]


def test_no_invoice_history_is_violation():
    assert check([])["violations"]


def test_void_and_draft_credit_notes_are_not_checked():
    for status in ("draft", "void"):
        result = check_credit_note_hsn([{**DOC, "status": status}], [], [], MAP, evidence_complete=False)
        assert result["passed"] and result["checked_lines"] == 0


def analytics_client(hsn="8504", invoice_hsn="8504"):
    analytics = MagicMock()
    def query(workspace_id, sql, **kwargs):
        if 'AS "document_id"' in sql:
            row = {"document_id": "CN1", "document_number": "CN-001", "date": "2026-09-10",
                   "status": "open", "location_id": "L1", "customer_id": "CUSTOMER1",
                   "customer_name": "Customer", "line_id": "LINE1", "hsn": hsn}
            row["gst_treatment"] = "Registered Business - Regular"
            if 'FROM "Invoices (Zoho Books)" D' in sql:
                return [{**row, "document_id": "INV1", "hsn": invoice_hsn, "date": "2025-03-01"}]
            return [row]
        if 'FROM "Locations' in sql:
            return [{"Location ID": "L1", "GSTIN": "GST1"}]
        if 'FROM "Invoices' in sql:
            return []
        return [{"CreditNotes ID": "CN1", "Credit Note Number": "CN-001", "Credit Note Date": "2026-09-10",
                 "Credit Note Status": "Open", "Location ID": "L1", "Customer ID": "CUSTOMER1"}]
    analytics.queries.execute.side_effect = query
    return analytics


def test_integrated_hsn_check_fails_all_scopes_and_markdown_has_details():
    analytics = analytics_client(invoice_hsn="8414")
    report = verify_gstr1(month="2026-09", analytics_client=analytics,
                         config=GSTR1VerificationConfig(e_invoice_applicable=False))
    assert report["complete"] and not report["overall_passed"]
    registration = report["gst_registrations"]["GST1"]
    assert not registration["passed"] and not registration["location_reports"]["L1"]["passed"]
    assert report["checks"]["credit_note_hsn"]["violations"]
    text = render_markdown_report(report)
    assert "### Credit-note HSN violations" in text and "8504" in text and "8414" in text
    queries = [call.args[1] for call in analytics.queries.execute.call_args_list]
    history = next(sql for sql in queries if 'FROM "Invoices (Zoho Books)" D' in sql)
    assert "2026-04-01" not in history and '"Customer ID" IN' in history


def test_hsn_export_failure_blocks_readiness():
    analytics = analytics_client()
    original = analytics.queries.execute.side_effect
    def query(workspace_id, sql, **kwargs):
        if 'AS "document_id"' in sql:
            raise RuntimeError("line export unavailable")
        return original(workspace_id, sql)
    analytics.queries.execute.side_effect = query
    report = verify_gstr1(month="2026-09", analytics_client=analytics)
    assert not report["complete"] and not report["overall_passed"]
    assert not report["checks"]["credit_note_hsn"]["complete"]


def test_integrated_match_passes_and_opt_out_avoids_line_exports():
    analytics = analytics_client()
    report = verify_gstr1(month="2026-09", analytics_client=analytics,
                         config=GSTR1VerificationConfig(e_invoice_applicable=False))
    assert report["overall_passed"] and report["checks"]["credit_note_hsn"]["checked_lines"] == 1
    analytics.queries.execute.reset_mock()
    skipped = verify_gstr1(month="2026-09", analytics_client=analytics,
                          config=GSTR1VerificationConfig(e_invoice_applicable=False, validate_credit_note_hsn=False))
    assert skipped["checks"]["credit_note_hsn"]["skipped"]
    assert analytics.queries.execute.call_count == 3


def test_force_refresh_still_uses_analytics_for_hsn_and_missing_client_is_incomplete():
    books = MagicMock()
    books.locations.list_all.return_value = [{"location_id": "L1", "tax_reg_no": "GST1"}]
    books.invoices.list_all.return_value = []
    books.credit_notes.list_all.return_value = [DOC]
    report = verify_gstr1(books, month="2026-09", force_refresh=True,
                         analytics_client=analytics_client(),
                         config=GSTR1VerificationConfig(e_invoice_applicable=False))
    assert report["complete"] and report["checks"]["credit_note_hsn"]["passed"]
    assert report["data_source"] == "books"
    missing = verify_gstr1(books, month="2026-09", force_refresh=True)
    assert not missing["complete"]


def test_invalid_export_identity_fails_closed():
    with pytest.raises(ValueError, match="HSN export"):
        _normalize({"document_id": "", "date": "2026-09-01", "status": "open"})


@pytest.mark.parametrize("treatment", ["B2C", "Consumer", "Unregistered Business", "business_none"])
def test_b2c_matches_another_customer_under_same_gstin(treatment):
    result = check([line(document_id="INV1", customer_id="OTHER", date="2026-04-10")],
                   [line(gst_treatment=treatment)])
    assert result["passed"]
    assert result["matched"][0]["sales_type"] == "B2C"
    assert result["matched"][0]["matching_customer_id"] == "OTHER"


@pytest.mark.parametrize("invoice_date,passed", [
    ("2026-03-09", False), ("2026-03-10", True), ("2026-09-10", True), ("2026-09-11", False)])
def test_b2c_six_month_window_is_anchored_to_credit_date(invoice_date, passed):
    result = check([line(document_id="INV1", customer_id="OTHER", date=invoice_date)],
                   [line(gst_treatment="Consumer")])
    assert result["passed"] is passed


@pytest.mark.parametrize("overrides", [{"location_id": "L2"}, {"status": "void"}, {"status": "draft"}])
def test_b2c_cannot_match_other_seller_gstin_void_or_draft(overrides):
    result = check([line(document_id="INV1", customer_id="OTHER", **overrides)],
                   [line(gst_treatment="Consumer")])
    assert result["violations"]


def test_transaction_consumer_overrides_registered_customer_and_fallback_is_explicit():
    invoices = [line(document_id="INV1", customer_id="OTHER")]
    result = check(invoices, [line(gst_treatment="Consumer", customer_gst_treatment="Registered Business - Regular")])
    assert result["passed"]
    fallback = check(invoices, [line(gst_treatment="", customer_gst_treatment="Consumer")])
    assert fallback["passed"]
    unknown = check(invoices, [line(gst_treatment="Unsupported", customer_gst_treatment="Consumer")])
    assert not unknown["complete"] and not unknown["violations"]
    missing = check(invoices, [line(gst_treatment="")])
    assert not missing["complete"]


def test_b2b_registered_transaction_is_not_relaxed_by_consumer_customer_record():
    result = check([line(document_id="INV1", customer_id="OTHER")],
                   [line(customer_gst_treatment="Consumer")])
    assert result["violations"] and result["complete"]


@pytest.mark.parametrize("credit_date,expected", [
    (date(2026, 8, 31), date(2026, 2, 28)), (date(2024, 8, 31), date(2024, 2, 29)),
    (date(2026, 1, 15), date(2025, 7, 15))])
def test_six_calendar_months_handles_month_end_leap_year_and_year_boundary(credit_date, expected):
    assert _six_months_before(credit_date) == expected


def test_b2c_missing_invoice_evidence_is_incomplete_instead_of_violation():
    result = check([line("", document_id="INV1", customer_id="OTHER")],
                   [line(gst_treatment="Consumer")])
    assert not result["complete"] and not result["violations"]


def test_history_export_includes_pooled_sales_without_customer_filter():
    analytics = analytics_client()
    verify_gstr1(month="2026-09", analytics_client=analytics,
                 config=GSTR1VerificationConfig(e_invoice_applicable=False))
    sql = next(call.args[1] for call in analytics.queries.execute.call_args_list
               if 'FROM "Invoices (Zoho Books)" D' in call.args[1])
    assert 'OR D."Invoice Date" >= \'2026-03-01\'' in sql
    assert 'AS "gst_treatment"' in sql and 'AS "customer_gst_treatment"' in sql


def test_integrated_b2c_match_is_recorded_in_markdown_and_all_results():
    analytics = analytics_client()
    original = analytics.queries.execute.side_effect
    def query(workspace_id, sql, **kwargs):
        rows = original(workspace_id, sql, **kwargs)
        if 'AS "document_id"' in sql:
            for row in rows:
                if row["document_id"] == "CN1":
                    row.update(gst_treatment="Consumer", customer_gst_treatment="Registered Business - Regular")
                else:
                    row.update(customer_id="OTHER", customer_name="Another customer", date="2026-04-10",
                               document_number="MATCH-001")
        return rows
    analytics.queries.execute.side_effect = query
    report = verify_gstr1(month="2026-09", analytics_client=analytics,
                         config=GSTR1VerificationConfig(e_invoice_applicable=False))
    assert report["overall_passed"]
    assert report["checks"]["credit_note_hsn"]["matched"][0]["sales_type"] == "B2C"
    markdown = render_markdown_report(report)
    assert "### Credit-note HSN matches" in markdown
    assert "B2C: any customer, preceding six months" in markdown
    assert "MATCH-001" in markdown and "Another customer" in markdown


def test_confirmed_financial_note_needs_no_hsn_evidence():
    result = check_credit_note_hsn([DOC], [], [], MAP, evidence_complete=False,
                                   financial_credit_note_ids=("CN1",))
    assert result["passed"] and result["complete"]
    assert result["checked_lines"] == 0 and not result["unverifiable"]
    assert result["financial_credit_notes"][0]["credit_note_number"] == "CN-001"


def test_financial_note_is_excluded_from_hsn_and_einvoice_but_retained_in_report():
    books = MagicMock()
    books.locations.list_all.return_value = [{"location_id": "L1", "tax_reg_no": "GST1"}]
    books.invoices.list_all.return_value = []
    books.credit_notes.list_all.return_value = [{**DOC, "einvoice_details": {"einvoice_status": "Yet To Be Pushed"}}]
    report = verify_gstr1(books, month="2026-09", force_refresh=True,
                         config=GSTR1VerificationConfig(financial_credit_note_ids=("CN1",)))
    assert report["complete"] and report["overall_passed"]
    assert report["credit_notes"]["count"] == 1
    hsn = report["checks"]["credit_note_hsn"]
    assert len(hsn["financial_credit_notes"]) == 1
    assert report["checks"]["einvoice_push"]["applicable_count"] == 0
    registration = report["gst_registrations"]["GST1"]
    assert registration["location_reports"]["L1"]["checks"]["credit_note_hsn"]["financial_credit_notes"]
    markdown = render_markdown_report(report)
    assert "### Financial credit notes — GST not applicable" in markdown
    assert "### Credit-note HSN unverifiable evidence" not in markdown


def test_financial_note_does_not_exempt_other_notes_or_draft_checks():
    result = check_credit_note_hsn([DOC, {**DOC, "creditnote_id": "CN2"}], [], [], MAP,
                                   evidence_complete=True, financial_credit_note_ids=("CN1",))
    assert not result["complete"]
    assert result["unverifiable"][0]["credit_note_id"] == "CN2"
    books = MagicMock()
    books.locations.list_all.return_value = []
    books.invoices.list_all.return_value = []
    books.credit_notes.list_all.return_value = [{**DOC, "status": "draft"}]
    report = verify_gstr1(books, month="2026-09", force_refresh=True,
                         config=GSTR1VerificationConfig(financial_credit_note_ids=("CN1",)))
    assert not report["checks"]["draft_documents"]["passed"]


@pytest.mark.parametrize("ids", ["CN1", ("",), (12,)])
def test_financial_credit_ids_are_validated(ids):
    with pytest.raises(ValueError, match="financial_credit_note_ids"):
        GSTR1VerificationConfig(financial_credit_note_ids=ids)
