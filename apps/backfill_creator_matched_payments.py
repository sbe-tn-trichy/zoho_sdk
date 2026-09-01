#!/usr/bin/env python3
"""Backfill Creator identifiers onto existing Books customer payments."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.matching import parse_date, to_decimal, to_text


def _normalized(value: Any) -> str:
    return "".join(character for character in to_text(value).casefold() if character.isalnum())


def build_native_payment_indexes(
    payments: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Mapping[str, Any]], Dict[str, Mapping[str, Any]]]:
    by_id: Dict[str, Mapping[str, Any]] = {}
    by_number: Dict[str, Mapping[str, Any]] = {}
    for payment in payments:
        payment_id = to_text(payment.get("payment_id") or payment.get("id"))
        payment_number = _normalized(payment.get("payment_number"))
        if payment_id:
            by_id[payment_id] = payment
        if payment_number:
            by_number[payment_number] = payment
    return by_id, by_number


def resolve_books_payment(
    creator: Mapping[str, Any],
    payments: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    by_number: Mapping[str, Mapping[str, Any]],
) -> Tuple[Optional[Mapping[str, Any]], str]:
    transaction_id = to_text(creator.get("books_transaction_id"))
    payment_number = _normalized(creator.get("books_payment_number"))
    direct = by_id.get(transaction_id) if transaction_id else None
    direct = direct or (by_number.get(payment_number) if payment_number else None)
    if direct is not None:
        return direct, "native_id_or_number"

    target_date = creator.get("date")
    target_amount = to_decimal(creator.get("amount"))
    target_reference = _normalized(creator.get("reference"))
    target_customer = _normalized(creator.get("customer_name"))
    candidates: List[Mapping[str, Any]] = []
    for payment in payments:
        amount = to_decimal(payment.get("amount"))
        if parse_date(payment.get("date")) != target_date:
            continue
        if amount is None or target_amount is None or abs(amount) != abs(target_amount):
            continue
        if _normalized(payment.get("reference_number")) != target_reference:
            continue
        if _normalized(payment.get("customer_name")) != target_customer:
            continue
        candidates.append(payment)
    if len(candidates) == 1:
        return candidates[0], "date_amount_reference_customer"
    if len(candidates) > 1:
        return None, "payment_ambiguous"
    return None, "payment_missing"


def _custom_field_values(payment: Mapping[str, Any]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for row in payment.get("custom_fields") or []:
        if isinstance(row, Mapping):
            key = to_text(row.get("api_name") or row.get("label")).casefold()
            if key:
                values[key] = to_text(row.get("value"))
    return values


def classify_links(
    payment: Mapping[str, Any], creator_record_id: str, creator_payment_id: str
) -> Tuple[str, List[str]]:
    values = _custom_field_values(payment)
    expected = {
        "cf_creator_record_id": creator_record_id,
        "cf_creator_payment_id": creator_payment_id,
    }
    if any(values.get(key) and values[key] != value for key, value in expected.items()):
        return "identifier_conflict", []
    missing = [key for key, value in expected.items() if values.get(key) != value]
    return ("ready", missing) if missing else ("already_linked", [])


@dataclass(frozen=True)
class BackfillConfig:
    execute: bool = False
    allow_batch: bool = False
    creator_record_id: Optional[str] = None
    creator_app: str = "order-management-new"
    creator_report: str = "matched"
    resume_from: Optional[Path] = None
    checkpoint_path: Path = Path(
        "output/collection_reconciliation/creator_books_payment_links.json"
    )

    def __post_init__(self) -> None:
        if self.execute and not self.creator_record_id and not self.allow_batch:
            raise ValueError("Batch execution requires --allow-batch.")


@dataclass
class BackfillResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        summary: Dict[str, int] = {"scanned": len(self.rows)}
        for row in self.rows:
            status = to_text(row.get("status")) or "unknown"
            summary[status] = summary.get(status, 0) + 1
        return summary


def _creator_values(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "books_transaction_id": to_text(record.get("Books_Transaction_Id")),
        "books_payment_number": to_text(record.get("PaymentNo")),
        "date": parse_date(record.get("Payment_Date")),
        "amount": to_decimal(record.get("Payment_Amount")),
        "reference": to_text(record.get("Reference")),
        "customer_name": to_text(record.get("Customer_Name")),
    }


def _write_checkpoint(path: Path, result: BackfillResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"summary": result.summary(), "rows": result.rows}, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class CreatorBooksPaymentLinkBackfill:
    def __init__(self, creator: Any, books: Any, config: BackfillConfig) -> None:
        self.creator = creator
        self.books = books
        self.config = config

    def run(self) -> BackfillResult:
        records = self.creator.get_all_records(
            self.config.creator_app, self.config.creator_report
        )
        if self.config.creator_record_id:
            records = [
                row for row in records
                if to_text(row.get("ID")) == self.config.creator_record_id
            ]
        resumed: Dict[str, Dict[str, Any]] = {}
        if self.config.resume_from and self.config.resume_from.exists():
            payload = json.loads(self.config.resume_from.read_text(encoding="utf-8"))
            resumed = {
                to_text(row.get("creator_record_id")): dict(row)
                for row in payload.get("rows", [])
                if to_text(row.get("creator_record_id"))
            }
        payments = self.books.customer_payments.list_all()
        by_id, by_number = build_native_payment_indexes(payments)
        rows: List[Dict[str, Any]] = []
        for record in records:
            record_id = to_text(record.get("ID"))
            if record_id in resumed and resumed[record_id].get("status") == "updated":
                rows.append(resumed[record_id])
                continue
            creator_payment_id = to_text(record.get("Payment_ID"))
            payment, source = resolve_books_payment(
                _creator_values(record), payments, by_id, by_number
            )
            row: Dict[str, Any] = {
                "creator_record_id": record_id,
                "match_source": source,
            }
            if payment is None:
                row["status"] = source
            else:
                status, _missing = classify_links(payment, record_id, creator_payment_id)
                row["books_payment_id"] = to_text(
                    payment.get("payment_id") or payment.get("id")
                )
                if status == "ready" and self.config.execute:
                    self.books.customer_payments.update(
                        row["books_payment_id"],
                        {
                            "custom_fields": [
                                {"label": "Creator Record ID", "value": record_id},
                                {"label": "Creator Payment ID", "value": creator_payment_id},
                            ]
                        },
                    )
                    row["status"] = "updated"
                else:
                    row["status"] = status
            rows.append(row)
        result = BackfillResult(rows)
        _write_checkpoint(self.config.checkpoint_path, result)
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-batch", action="store_true")
    parser.add_argument("--creator-record-id")
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--creator-report", default="matched")
    parser.add_argument("--resume-from", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = BackfillConfig(
        execute=args.execute,
        allow_batch=args.allow_batch,
        creator_record_id=args.creator_record_id,
        creator_app=args.creator_app,
        creator_report=args.creator_report,
        resume_from=args.resume_from,
    )
    result = CreatorBooksPaymentLinkBackfill(
        get_creator_client(), get_books_client(), config
    ).run()
    print(json.dumps(result.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
