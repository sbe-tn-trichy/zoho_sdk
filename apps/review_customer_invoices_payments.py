#!/usr/bin/env python3
"""Export a read-only customer invoice/payment verification report."""

import argparse
import csv
import json
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.customer_invoice_payment_review import review_customer_invoices_payments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-id", required=True)
    args = parser.parse_args(argv)
    result = review_customer_invoices_payments(get_books_client(), args.customer_id)
    destination = Path("output/customer_invoice_payment_review")
    destination.mkdir(parents=True, exist_ok=True)
    invoice_path = destination / f"{args.customer_id}_invoices.csv"
    with invoice_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Date", "Invoice Number", "Invoice Value", "CD Applied", "Payment"])
        for row in result.invoices:
            cd = f"{row['cd_applied']:g}%" if row["cd_applied"] else "0"
            writer.writerow([row["date"], row["invoice_number"], f"{row['invoice_value']:.2f}", cd, f"{row['payment']:.2f}"])
    payment_path = destination / f"{args.customer_id}_payment_allocations.csv"
    with payment_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Payment Date", "Payment Number", "Invoice Number", "Payment Total (repeated per allocation)", "Amount Applied", "Unused Amount (repeated per allocation)"])
        for row in result.allocations:
            writer.writerow([row["date"], row["payment_number"], row["invoice_number"], row["payment_amount"], row["amount_applied"], row["unused_amount"]])
    summary = {"customer_id": result.customer_id, "customer": result.customer_name,
        "invoice_count": len(result.invoices), "allocation_rows": len(result.allocations),
        "invoice_value": str(sum(row["invoice_value"] for row in result.invoices)),
        "payments_applied": str(sum(row["payment"] for row in result.invoices)),
        "issues": result.issues, "invoices": str(invoice_path), "payments": str(payment_path)}
    (destination / f"{args.customer_id}_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
