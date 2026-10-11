from unittest.mock import MagicMock

from workflows.gstr1_verification import render_markdown_report, verify_gstr1


def result():
    client = MagicMock()
    client.locations.list_all.return_value = [{"location_id": "L1", "tax_reg_no": "TEST", "location_name": "Branch"}]
    client.invoices.list_all.return_value = [{"invoice_id": "I1", "invoice_number": "INV-001",
        "date": "2026-09-01", "status": "sent", "location_id": "L1",
        "total_taxable_amount": 100, "taxes": [], "tax_total": 0, "total": 100,
        "einvoice_details": {"einvoice_status": "Yet To Be Pushed"}}]
    client.credit_notes.list_all.return_value = []
    return verify_gstr1(client, month="2026-09", force_refresh=True)


def test_report_includes_identity_checks_locations_and_evidence():
    report = render_markdown_report(result(), gstin_aliases={"TEST": "SBE"})
    assert "# GSTR-1 verification — 2026-09" in report
    assert "## SBE — TEST" in report
    assert "**Result:** FAIL" in report
    assert "**Invoices:** 1" in report
    assert "### Locations" in report and "Branch" in report
    assert "### E-invoice exceptions" in report
    assert "INV-001" in report and "Yet To Be Pushed" in report
    assert "Number sequence and chronology | PASS" in report


def test_incomplete_report_does_not_present_success():
    data = result()
    data["complete"] = False
    data["fetch_errors"] = [{"source": "invoices", "error": "bad | response\nretry <now>"}]
    text = render_markdown_report(data)
    assert "**Result:** INCOMPLETE" in text
    assert "## Fetch errors" in text
    assert "bad \\| response retry &lt;now&gt;" in text


def test_all_sequence_error_shapes_and_voids_are_rendered():
    data = result()
    registration = data["gst_registrations"]["TEST"]
    sequence = registration["checks"]["number_sequence"]
    sequence.update(missing=[{"number": "INV-002"}],
        duplicates=[{"documents": [{"number": "INV-003", "id": "A"}, {"number": "INV-003", "id": "B"}]}],
        out_of_chronology=[{"number": "INV-004", "preceded_by": "INV-003"}],
        unparseable_numbers=[{"number": "invalid"}], invalid_dates=[{"date": "invalid-date"}],
        inconsistent_width=[{"widths": [2, 3]}])
    registration["void_documents"] = [{"number": "INV-005", "status": "void"}]
    text = render_markdown_report(data)
    for value in ["INV-002", "INV-003", "INV-004", "invalid-date", "2; 3", "INV-005"]:
        assert value in text


def test_empty_report_and_disabled_einvoice():
    data = result()
    check = data["gst_registrations"]["TEST"]["checks"]["einvoice_push"]
    check.update(skipped=True, passed=True, exceptions=[])
    assert "E-invoice registration | SKIPPED" in render_markdown_report(data)
    data["gst_registrations"] = {}
    assert "No registration data was returned." in render_markdown_report(data)


def test_saved_registration_report():
    full = result()
    data = {**full["gst_registrations"]["TEST"], "period": full["period"],
            "complete": True, "data_source": "analytics", "alias": "SBE"}
    text = render_markdown_report(data)
    assert "## SBE — TEST" in text
    assert "last synchronization" in text
