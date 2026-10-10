"""Markdown presentation of GSTR-1 readiness and financial totals."""
from typing import Any, Mapping


def render_markdown_report(report: Mapping[str, Any]) -> str:
    """Render registration and location checks with net GST amounts in INR."""
    lines = ['# GSTR-1 Filing Check Report', '', f"Period: {report['period']['month']}", '', f"Data retrieval: {'Complete' if report['complete'] else 'Incomplete'}", '']
    for key, registration in report['gst_registrations'].items():
        lines += [f'## GSTIN: {key}', '', f"Checks: {'Passed' if registration['passed'] and report['complete'] else 'Failed or incomplete'}", '', '| Check | Result |', '|---|---|']
        for name, check in registration['checks'].items():
            lines.append(f"| {name.replace('_', ' ').title()} | {'Passed' if check['passed'] else 'Failed'} |")
        summary = registration['financial_summary']
        lines += ['', f"Amounts: {'Complete' if summary['complete'] else 'Incomplete — partial totals only'}", '', '| Documents | Total Taxable | IGST | CGST | SGST | Total |', '|---|---:|---:|---:|---:|---:|']
        keys = ('total_taxable', 'igst', 'cgst', 'sgst', 'total')
        for kind, label in (('invoices', 'Invoices'), ('credit_notes', 'Credit notes (deduct)'), ('net', 'Net total')):
            lines.append('| ' + label + ' | ' + ' | '.join(f'{summary[kind][k]:,.2f}' for k in keys) + ' |')
        lines += ['', '| Location | Total Taxable | IGST | CGST | SGST | Total |', '|---|---:|---:|---:|---:|---:|']
        for location in registration['location_reports'].values():
            values = location['financial_summary']['net']
            name = str(location['location_name'] or 'Unassigned').replace('|', '\\|').replace('\n', ' ')
            lines.append('| ' + name + ' | ' + ' | '.join(f'{values[k]:,.2f}' for k in keys) + ' |')
        lines += ['']
    lines += ['All amounts are INR. Credit notes are deducted; draft and void documents are excluded. Total uses the Books document amount, including rounding and adjustments.', '', 'This read-only check does not file a return.', '']
    if report['fetch_errors']:
        lines += ['## Retrieval errors', '']
        for error in report['fetch_errors']:
            lines.append(f"- {error['source']}: {error['error']}")
    return '\n'.join(lines) + '\n'
