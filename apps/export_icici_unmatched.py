#!/usr/bin/env python3
"""Export live uncategorized ICICI Books bank transactions to an audit CSV."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.core.matching import get_bank_reference


def main() -> None:
    account_id = Config.BANK_ACCOUNT_ICICI
    transactions = get_books_client().bank_transactions.list_all(
        params={
            "account_id": account_id,
            "filter_by": "Status.Uncategorized",
            "sort_column": "date",
            "sort_order": "D",
        }
    )

    output_path = Path("output/bank_reconciliation/icici_unmatched_transactions.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "transaction_id",
        "date",
        "amount",
        "debit_or_credit",
        "reconciliation_reference",
        "zoho_reference_number",
        "reference_source",
        "description",
        "payee",
        "transaction_type",
        "status",
        "source",
        "reconcile_status",
        "account_id",
        "account_name",
        "report_generated_at",
    ]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for transaction in transactions:
            raw_reference = transaction.get("reference_number") or ""
            reconciliation_reference = get_bank_reference(transaction, account_id) or ""
            writer.writerow(
                {
                    "transaction_id": transaction.get("transaction_id") or transaction.get("id") or "",
                    "date": transaction.get("date") or "",
                    "amount": transaction.get("amount") or 0,
                    "debit_or_credit": transaction.get("debit_or_credit") or "",
                    "reconciliation_reference": reconciliation_reference,
                    "zoho_reference_number": raw_reference,
                    "reference_source": (
                        "description_upi"
                        if str(reconciliation_reference) != str(raw_reference)
                        else "zoho_reference_number"
                    ),
                    "description": transaction.get("description") or "",
                    "payee": transaction.get("payee") or "",
                    "transaction_type": transaction.get("transaction_type") or "",
                    "status": transaction.get("status") or "",
                    "source": transaction.get("source") or "",
                    "reconcile_status": transaction.get("reconcile_status") or "",
                    "account_id": transaction.get("account_id") or account_id,
                    "account_name": transaction.get("account_name") or "",
                    "report_generated_at": generated_at,
                }
            )

    print(f"{output_path.resolve()}\t{len(transactions)}")


if __name__ == "__main__":
    main()
