#!/usr/bin/env python3
"""Backfill Creator payment checkpoints from existing Books customer payments."""

from __future__ import annotations

import argparse
import json
import os
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


def _require_creator_update_success(response: Any) -> None:
    if not isinstance(response, Mapping):
        raise RuntimeError("Creator returned an invalid update response.")
    payloads = [response]
    data = response.get("data")
    if isinstance(data, Mapping):
        payloads.append(data)
    elif isinstance(data, list):
        payloads.extend(row for row in data if isinstance(row, Mapping))
    for payload in payloads:
        code = payload.get("code")
        if code is not None and str(code).strip() not in {"0", "3000"}:
            raise RuntimeError(f"Creator rejected the update (code={code}).")


def _verify_creator_fields(
    creator: Any,
    creator_app: str,
    record_id: str,
    expected: Mapping[str, str],
) -> None:
    response = creator.get_records(
        creator_app,
        "All_Payments",
        params={"criteria": f"ID == {record_id}", "field_config": "all"},
    )
    rows = response.get("data", []) if isinstance(response, Mapping) else []
    record = next(
        (
            row for row in rows
            if isinstance(row, Mapping) and to_text(row.get("ID")) == record_id
        ),
        None,
    )
    if record is None or any(
        to_text(record.get(key)) != value for key, value in expected.items()
    ):
        raise RuntimeError("Creator checkpoint verification failed.")


def _write_result(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_backfill(
    creator: Any,
    books: Any,
    *,
    creator_app: str,
    execute: bool = False,
    allow_batch: bool = False,
    creator_record_id: Optional[str] = None,
    checkpoint_path: Optional[Path] = None,
    resume_from: Optional[Path] = None,
) -> Dict[str, Any]:
    if execute and not creator_record_id and not allow_batch:
        raise ValueError("Batch execution requires --allow-batch.")
    records = creator.get_all_records(creator_app, "Online_Payments")
    if creator_record_id:
        records = [
            record for record in records
            if to_text(record.get("ID")) == creator_record_id
        ]
    resumed: Dict[str, Mapping[str, Any]] = {}
    if resume_from and resume_from.exists():
        payload = json.loads(resume_from.read_text(encoding="utf-8"))
        resumed = {
            to_text(row.get("record_id")): row
            for row in payload.get("rows", [])
            if isinstance(row, Mapping) and to_text(row.get("record_id"))
        }
    payments = books.customer_payments.list_all()
    rows = []
    for record in records:
        record_id = to_text(record.get("ID"))
        if record_id in resumed and resumed[record_id].get("status") == "updated":
            rows.append(dict(resumed[record_id]))
            if checkpoint_path:
                _write_result(
                    checkpoint_path, {"summary": _summary(rows), "rows": rows}
                )
            continue
        payment, source = find_books_payment(_creator_values(record), payments)
        row = {"record_id": record_id, "status": source}
        if payment is not None:
            expected = {
                "Books_Transaction_Id": to_text(payment.get("payment_id")),
                "PaymentNo": to_text(payment.get("payment_number")),
            }
            row.update(expected)
            if execute:
                try:
                    response = creator.update_records(
                        creator_app,
                        "All_Payments",
                        {"data": expected},
                        record_id=row["record_id"],
                    )
                    _require_creator_update_success(response)
                    _verify_creator_fields(
                        creator, creator_app, row["record_id"], expected
                    )
                    row["status"] = "updated"
                except Exception as exc:
                    row["status"] = "update_failed"
                    row["error"] = str(exc)
            else:
                row["status"] = "planned"
        rows.append(row)
        if checkpoint_path:
            partial = {"summary": _summary(rows), "rows": rows}
            _write_result(checkpoint_path, partial)
    summary = _summary(rows)
    return {"summary": summary, "rows": rows}


def _summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {"scanned": len(rows)}
    for row in rows:
        status = to_text(row.get("status")) or "unknown"
        summary[status] = summary.get(status, 0) + 1
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-batch", action="store_true")
    parser.add_argument("--creator-record-id")
    parser.add_argument("--resume-from", type=Path)
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
        allow_batch=args.allow_batch,
        creator_record_id=args.creator_record_id,
        checkpoint_path=args.output,
        resume_from=args.resume_from,
    )
    _write_result(args.output, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
