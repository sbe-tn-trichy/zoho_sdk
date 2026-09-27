"""Format customer payment date mismatch reports as Markdown and CSV."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List


def render_markdown_report(payload: Dict[str, Any]) -> str:
    """Render a human-readable Markdown audit report."""
    result = payload.get("result") or payload
    checked_at = payload.get("checked_at", "")
    filters = payload.get("filters", {})

    lines: List[str] = [
        "# Customer Payment vs Applied Date Audit Report",
        "",
        f"- **Checked At (UTC)**: {checked_at}",
        f"- **Payments Scanned**: {result.get('payments_scanned', 0)}",
        f"- **Mismatched Payments**: {result.get('mismatched_payments_count', 0)}",
        f"- **Mismatched Invoice Applications**: {result.get('total_mismatched_applications', 0)}",
        f"- **Tolerance (Days)**: {result.get('tolerance_days', 0)}",
    ]

    if filters:
        filter_strs = [f"{k}: {v}" for k, v in filters.items() if v is not None]
        if filter_strs:
            lines.append(f"- **Filters Applied**: {', '.join(filter_strs)}")

    lines.append("")

    mismatches = result.get("mismatches", [])
    if not mismatches:
        lines.append("No customer payments with different applied dates were found.")
        return "\n".join(lines) + "\n"

    lines.extend([
        "## Mismatched Payment Allocations",
        "",
        "| Payment # | Payment Date | Customer | Invoice # | Invoice Date | Applied Date | Diff (Days) | Amount Applied | Reference |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    for pmt in mismatches:
        pmt_num = pmt.get("payment_number") or pmt.get("payment_id")
        pmt_date = pmt.get("payment_date", "")
        cust_name = pmt.get("customer_name", "")
        ref = pmt.get("reference_number", "")

        for app in pmt.get("mismatched_applications", []):
            inv_num = app.get("invoice_number") or app.get("invoice_id", "")
            inv_date = app.get("invoice_date") or "-"
            applied_date = app.get("applied_date", "")
            days_diff = app.get("days_difference", 0)
            diff_str = f"+{days_diff}d" if days_diff > 0 else f"{days_diff}d"
            amt = app.get("amount_applied", "0.00")

            lines.append(
                f"| {pmt_num} | {pmt_date} | {cust_name} | {inv_num} | {inv_date} | {applied_date} | {diff_str} | ₹{amt} | {ref} |"
            )

    lines.append("")
    return "\n".join(lines) + "\n"


def render_csv_report(payload: Dict[str, Any]) -> str:
    """Render a CSV audit report."""
    result = payload.get("result") or payload
    mismatches = result.get("mismatches", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Payment ID",
        "Payment Number",
        "Payment Date",
        "Customer ID",
        "Customer Name",
        "Payment Amount",
        "Payment Mode",
        "Reference Number",
        "Invoice ID",
        "Invoice Number",
        "Invoice Date",
        "Applied Date",
        "Days Difference",
        "Mismatch Type",
        "Amount Applied",
    ])

    for pmt in mismatches:
        for app in pmt.get("mismatched_applications", []):
            writer.writerow([
                pmt.get("payment_id"),
                pmt.get("payment_number"),
                pmt.get("payment_date"),
                pmt.get("customer_id"),
                pmt.get("customer_name"),
                pmt.get("payment_amount"),
                pmt.get("payment_mode"),
                pmt.get("reference_number"),
                app.get("invoice_id"),
                app.get("invoice_number"),
                app.get("invoice_date"),
                app.get("applied_date"),
                app.get("days_difference"),
                app.get("mismatch_type"),
                app.get("amount_applied"),
            ])

    return output.getvalue()
