"""Markdown presentation of GSTR-1 readiness evidence."""

from typing import Any, Mapping, Sequence


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, Mapping):
        value = "; ".join(f"{key.replace('_', ' ')}: {_cell(item)}" for key, item in value.items())
    elif isinstance(value, (list, tuple)):
        value = "; ".join(_cell(item) for item in value)
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def _table(lines: list[str], rows: Sequence[Mapping[str, Any]],
           columns: Sequence[tuple[str, str]]) -> None:
    lines.extend(["", "| " + " | ".join(label for _, label in columns) + " |",
                  "| " + " | ".join("---" for _ in columns) + " |"])
    lines.extend("| " + " | ".join(_cell(row.get(key)) for key, _ in columns) + " |" for row in rows)
    lines.append("")


def _status(passed: bool, complete: bool) -> str:
    return "INCOMPLETE" if not complete else "PASS" if passed else "FAIL"


def render_markdown_report(report: Mapping[str, Any], *,
                           gstin_aliases: Mapping[str, str] | None = None) -> str:
    """Render a full verification result or one saved registration report.

    Aliases are display labels; the GSTIN remains the registration identity.
    Fetch errors always take precedence over passing check results.
    """
    aliases = gstin_aliases or {}
    period = report["period"]
    complete = bool(report["complete"])
    passed = bool(report.get("overall_passed", report.get("passed", False)))
    lines = [f"# GSTR-1 verification — {period['month']}", "",
             f"**Result:** {_status(passed, complete)}  ",
             f"**Source:** {_cell(report['data_source'])}  ",
             f"**Period:** {_cell(period['start_date'])} to {_cell(period['end_date'])}  ",
             f"**Sequence scope:** {_cell(period['sequence_scope_start'])} to {_cell(period['sequence_scope_end'])}", ""]
    if report["data_source"] == "analytics":
        lines.extend(["Analytics reflects its last synchronization. Use force refresh for current Books evidence.", ""])
    errors = report.get("fetch_errors", [])
    if errors:
        lines.extend(["## Fetch errors", "", "Verification is incomplete; passing checks do not establish readiness."])
        _table(lines, errors, [("source", "Source"), ("error", "Error")])
    registrations = report.get("gst_registrations")
    if registrations is None:
        registrations = {str(report.get("gstin") or "Unknown registration"): report}
    if not registrations:
        lines.extend(["No registration data was returned.", ""])
    for key, registration in registrations.items():
        gstin = str(registration.get("gstin") or key)
        alias = aliases.get(gstin) or registration.get("alias")
        label = f"{alias} — {gstin}" if alias else gstin
        checks = registration["checks"]
        einvoice = checks["einvoice_push"]
        hsn = checks.get("credit_note_hsn")
        lines.extend([f"## {_cell(label)}", "",
                      f"**Result:** {_status(registration['passed'], complete)}  ",
                      f"**Invoices:** {registration['invoices']['count']}  ",
                      f"**Credit notes:** {registration['credit_notes']['count']}  ",
                      f"**Void documents:** {len(registration.get('void_documents', []))}", ""])
        check_rows = [
            {"check": "Draft documents", "result": "PASS" if checks["draft_documents"]["passed"] else "FAIL"},
            {"check": "Number sequence and chronology", "result": "PASS" if checks["number_sequence"]["passed"] else "FAIL"},
            {"check": "E-invoice registration", "result": "SKIPPED" if einvoice["skipped"] else "PASS" if einvoice["passed"] else "FAIL"},
        ]
        if hsn:
            check_rows.append({"check": "Credit-note HSN against invoice history",
                               "result": "SKIPPED" if hsn["skipped"] else _status(hsn["passed"], hsn["complete"])})
        _table(lines, check_rows, [("check", "Check"), ("result", "Result")])
        if hsn and not hsn["skipped"]:
            lines.extend([f"HSN evidence (Analytics): {hsn['checked_lines']} credit-note lines checked; "
                          f"{len(hsn['violations'])} violations; {len(hsn['unverifiable'])} unverifiable records; "
                          f"{len(hsn.get('financial_credit_notes', []))} financial credit notes excluded (GST not applicable).", "",
                          "B2B credits require the HSN on a prior invoice for the same customer. "
                          "B2C credits reduce pooled sales and require the HSN on any customer's invoice in the "
                          "preceding six calendar months. Both rules stay within the seller GSTIN and exclude future, "
                          "draft and void invoices. Transaction GST treatment takes precedence over the customer record.", ""])
            if hsn.get("matched"):
                lines.append("### Credit-note HSN matches")
                _table(lines, hsn["matched"], [("credit_note_number", "Credit note"), ("customer_name", "Customer"),
                       ("hsn", "HSN"), ("rule", "Rule"), ("matching_invoice_number", "Matching invoice"),
                       ("matching_invoice_date", "Invoice date"), ("matching_customer_name", "Invoice customer")])
        if einvoice["skipped"]:
            lines.extend(["E-invoicing is disabled by workflow configuration.", ""])
        else:
            lines.extend([f"E-invoice evidence: {len(einvoice['pushed'])} registered; "
                          f"{len(einvoice['exceptions'])} exceptions; "
                          f"{len(einvoice['not_applicable_or_not_returned'])} not applicable or not returned.", ""])
        locations = registration.get("location_reports", {})
        if locations:
            lines.append("### Locations")
            _table(lines, [{"location": loc.get("location_name") or loc.get("location_id"),
                           "invoices": loc["invoices"]["count"], "credits": loc["credit_notes"]["count"],
                           "result": _status(loc["passed"], complete)} for loc in locations.values()],
                   [("location", "Location"), ("invoices", "Invoices"), ("credits", "Credit notes"), ("result", "Result")])
        summary = registration.get("financial_summary")
        if summary:
            lines.extend(["### Financial amounts (INR)", "",
                          "Amounts: " + ("Complete" if summary["complete"] else "Incomplete ? partial totals only")])
            amount_keys = ("total_taxable", "igst", "cgst", "sgst", "total")
            columns = [("documents", "Documents"), *[(key, ("Total Taxable" if key == "total_taxable" else "Total" if key == "total" else key.upper())) for key in amount_keys]]
            _table(lines, [{"documents": label, **{key: f"{summary[kind][key]:,.2f}" for key in amount_keys}}
                           for kind, label in (("invoices", "Invoices"), ("credit_notes", "Credit notes (deduct)"), ("net", "Net total"))], columns)
            _table(lines, [{"location": loc.get("location_name") or loc.get("location_id"),
                            **{key: f"{loc['financial_summary']['net'][key]:,.2f}" for key in amount_keys}}
                           for loc in locations.values() if loc.get("financial_summary")],
                   [("location", "Location"), *columns[1:]])
            lines.extend(["All amounts are INR. Credit notes are deducted; draft and void documents are excluded. "
                          "Total uses the Books document amount, including rounding and adjustments.", ""])
        findings = {"Draft documents": checks["draft_documents"]["documents"],
                    **{key.replace("_", " ").capitalize(): rows for key, rows in checks["number_sequence"].items() if key != "passed"},
                    "E-invoice exceptions": einvoice["exceptions"],
                    "E-invoice not applicable or not returned": einvoice["not_applicable_or_not_returned"],
                    "Void documents": registration.get("void_documents", [])}
        if hsn:
            findings["Credit-note HSN violations"] = hsn["violations"]
            findings["Credit-note HSN unverifiable evidence"] = hsn["unverifiable"]
            findings["Financial credit notes — GST not applicable"] = hsn.get("financial_credit_notes", [])
        for title, rows in findings.items():
            if not rows:
                continue
            lines.append(f"### {title}")
            columns = list(dict.fromkeys(field for row in rows for field in row))
            _table(lines, rows, [(field, field.replace("_", " ").capitalize()) for field in columns])
    for warning in report.get("warnings", []):
        lines.extend([f"Warning: {_cell(warning)}", ""])
    return "\n".join(lines).rstrip() + "\n"
