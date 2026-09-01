#!/usr/bin/env python3
"""Backfill Creator payment checkpoints from existing Books customer payments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.matching import parse_date, to_decimal, to_text


def _normalized(value: Any) -> str:
    return "".join(character for character in to_text(value).casefold() if character.isalnum())


def find_books_payment(
    values: Mapping[str, Any], payments: Sequence[Mapping[str, Any]]
) -> Tuple[Optional[Mapping[str, Any]], str]:
    existing_id = to_text(values.get("books_payment_id"))
    existing_number = _normalized(values.get("books_payment_number"))
    direct = [
        payment
        for payment in payments
        if (existing_id and to_text(payment.get("payment_id")) == existing_id)
        or (
            existing_number
            and _normalized(payment.get("payment_number")) == existing_number
        )
    ]
    direct_ids = {to_text(row.get("payment_id")) for row in direct}
    direct_ids.discard("")
    if len(direct_ids) == 1:
        return direct[0], "existing_identifier"
    if len(direct_ids) > 1:
        return None, "identifier_conflict"

    expected_date = values.get("date")
    expected_amount = to_decimal(values.get("amount"))
    expected_reference = _normalized(values.get("reference"))
    expected_customer = to_text(values.get("customer_id"))
    if not expected_date or expected_amount is None or not expected_reference or not expected_customer:
        return None, "creator_data_incomplete"
    candidates = []
    for payment in payments:
        amount = to_decimal(payment.get("amount"))
        if to_text(payment.get("customer_id")) != expected_customer:
            continue
        if parse_date(payment.get("date")) != expected_date:
            continue
        if amount is None or abs(amount) != abs(expected_amount):
            continue
        if _normalized(payment.get("reference_number")) != expected_reference:
            continue
        candidates.append(payment)
    unique = {
        to_text(payment.get("payment_id")): payment
        for payment in candidates
        if to_text(payment.get("payment_id"))
    }
    if len(unique) == 1:
        return next(iter(unique.values())), "exact_customer_date_amount_reference"
    if len(unique) > 1:
        return None, "payment_ambiguous"
    return None, "payment_missing"


def _creator_values(record: Mapping[str, Any]) -> Dict[str, Any]:
    customer = record.get("Customer_Name")
    customer = customer if isinstance(customer, Mapping) else {}
    return {
        "date": parse_date(record.get("Payment_Date")),
        "amount": to_decimal(record.get("Payment_Amount")),
        "reference": to_text(record.get("Reference")),
        "customer_id": to_text(customer.get("Customer_Id") or customer.get("ID")),
        "books_payment_id": to_text(record.get("Books_Transaction_Id")),
        "books_payment_number": to_text(record.get("PaymentNo")),
    }


def run_backfill(
    creator: Any,
    books: Any,
    *,
    creator_app: str,
    execute: bool = False,
) -> Dict[str, Any]:
    records = creator.get_all_records(creator_app, "Online_Payments")
    payments = books.customer_payments.list_all()
    rows = []
    for record in records:
        payment, source = find_books_payment(_creator_values(record), payments)
        row = {"record_id": to_text(record.get("ID")), "status": source}
        if payment is not None:
            expected = {
                "Books_Transaction_Id": to_text(payment.get("payment_id")),
                "PaymentNo": to_text(payment.get("payment_number")),
            }
            row.update(expected)
            if execute:
                creator.update_records(
                    creator_app,
                    "All_Payments",
                    {"data": expected},
                    record_id=row["record_id"],
                )
                row["status"] = "updated"
            else:
                row["status"] = "planned"
        rows.append(row)
    summary: Dict[str, int] = {"scanned": len(rows)}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    return {"summary": summary, "rows": rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/collection_reconciliation/online_payment_books_backfill.json"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_backfill(
        get_creator_client(),
        get_books_client(),
        creator_app=args.creator_app,
        execute=args.execute,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
