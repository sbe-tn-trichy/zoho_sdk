"""Backfill Creator identifiers onto existing Books customer payments."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from workflows.core.matching import parse_date, to_decimal, to_text
from zoho.helpers.transactions import unwrap_record


def _normalized(value: Any) -> str:
    return "".join(character for character in to_text(value).casefold() if character.isalnum())


def build_native_payment_indexes(
    payments: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Mapping[str, Any]], Dict[str, List[Mapping[str, Any]]]]:
    by_id: Dict[str, Mapping[str, Any]] = {}
    by_number: Dict[str, List[Mapping[str, Any]]] = {}
    for payment in payments:
        payment_id = to_text(payment.get("payment_id") or payment.get("id"))
        payment_number = _normalized(payment.get("payment_number"))
        if payment_id:
            by_id[payment_id] = payment
        if payment_number:
            by_number.setdefault(payment_number, []).append(payment)
    return by_id, by_number


def resolve_books_payment(
    creator: Mapping[str, Any],
    payments: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    by_number: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Tuple[Optional[Mapping[str, Any]], str]:
    transaction_id = to_text(creator.get("books_transaction_id"))
    payment_number = _normalized(creator.get("books_payment_number"))
    id_match = by_id.get(transaction_id) if transaction_id else None
    number_matches = list(by_number.get(payment_number, ())) if payment_number else []
    if id_match is not None:
        id_match_id = to_text(id_match.get("payment_id") or id_match.get("id"))
        if number_matches and not any(
            to_text(candidate.get("payment_id") or candidate.get("id")) == id_match_id
            for candidate in number_matches
        ):
            return None, "identifier_conflict"
        return id_match, "native_id_or_number"
    if len(number_matches) > 1:
        return None, "payment_ambiguous"
    number_match = number_matches[0] if number_matches else None
    if number_match is not None:
        return number_match, "native_id_or_number"
    if payment_number:
        return None, "payment_number_missing"

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
    values: Dict[str, str] = {
        key: to_text(payment.get(key))
        for key in ("cf_creator_record_id", "cf_creator_payment_id")
        if to_text(payment.get(key))
    }
    for row in (payment.get("custom_fields") or payment.get("custom_fields_list") or []):
        if isinstance(row, Mapping):
            key = to_text(row.get("api_name") or row.get("label")).casefold()
            key = {
                "creator record id": "cf_creator_record_id",
                "creator payment id": "cf_creator_payment_id",
            }.get(key, key)
            if key:
                values[key] = to_text(row.get("value"))
    return values


def classify_links(
    payment: Mapping[str, Any], creator_record_id: str, creator_payment_id: str
) -> Tuple[str, List[str]]:
    if not creator_record_id or not creator_payment_id:
        return "creator_data_incomplete", []
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
    location_id: str = ""
    execute: bool = False
    allow_batch: bool = False
    creator_record_id: Optional[str] = None
    creator_app: str = "order-management-new"
    creator_report: str = "matched"
    creator_crosscheck_report: str = "All_Payments"
    books_request_interval_seconds: float = 0.8
    resume_from: Optional[Path] = None
    checkpoint_path: Path = Path(
        "output/collection_reconciliation/creator_books_payment_links.json"
    )

    def __post_init__(self) -> None:
        if not self.location_id.strip():
            raise ValueError("A Books location ID is required.")
        if self.books_request_interval_seconds < 0:
            raise ValueError("Books request interval cannot be negative.")
        if self.execute and not self.creator_record_id and not self.allow_batch:
            raise ValueError("Batch execution requires --allow-batch.")


@dataclass
class BackfillResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)
    oldest_creator_date: Optional[str] = None
    sequence_gaps: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        summary: Dict[str, int] = {"scanned": len(self.rows)}
        for row in self.rows:
            status = to_text(row.get("status")) or "unknown"
            summary[status] = summary.get(status, 0) + 1
        return summary


def _creator_values(record: Mapping[str, Any]) -> Dict[str, Any]:
    customer = record.get("Customer_Name")
    if isinstance(customer, Mapping):
        customer = customer.get("zc_display_value") or customer.get("Name")
    return {
        "books_transaction_id": to_text(record.get("Books_Transaction_Id")),
        "books_payment_number": to_text(record.get("PaymentNo")),
        "date": parse_date(record.get("Payment_Date")),
        "amount": to_decimal(record.get("Payment_Amount")),
        "reference": to_text(record.get("Reference")),
        "customer_name": to_text(customer),
    }


def _crosschecked_values(
    record: Mapping[str, Any], canonical: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    values = _creator_values(record)
    if canonical is not None:
        canonical_values = _creator_values(canonical)
        for key in ("books_transaction_id", "books_payment_number"):
            if canonical_values[key]:
                values[key] = canonical_values[key]
    return values


def find_creator_sequence_gaps(
    matched: Sequence[Mapping[str, Any]],
    crosscheck: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Report absent matched-report Payment_ID ranges and their Creator cross-check."""
    matched_ids = sorted({
        int(value) for row in matched
        if (value := to_text(row.get("Payment_ID"))).isdigit()
    })
    all_ids = sorted({
        int(value) for row in crosscheck
        if (value := to_text(row.get("Payment_ID"))).isdigit()
    })
    gaps: List[Dict[str, Any]] = []
    for left, right in zip(matched_ids, matched_ids[1:]):
        if right - left <= 1:
            continue
        found = [value for value in all_ids if left < value < right]
        missing_ranges = []
        previous = left
        for value in [*found, right]:
            if value > previous + 1:
                missing_ranges.append({"first": previous + 1, "last": value - 1})
            previous = value
        gaps.append({
            "first": left + 1,
            "last": right - 1,
            "found_in_creator": found,
            "missing_in_creator": missing_ranges,
        })
    return gaps


def _write_checkpoint(path: Path, result: BackfillResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({
            "summary": result.summary(),
            "oldest_creator_date": result.oldest_creator_date,
            "sequence_gaps": result.sequence_gaps,
            "rows": result.rows,
        }, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


class CreatorBooksPaymentLinkBackfill:
    def __init__(self, creator: Any, books: Any, config: BackfillConfig) -> None:
        self.creator = creator
        self.books = books
        self.config = config
        self._last_books_request_at = 0.0

    def _books_request(self, operation: Any, *args: Any) -> Any:
        for attempt in range(4):
            wait = self.config.books_request_interval_seconds - (
                time.monotonic() - self._last_books_request_at
            )
            if wait > 0:
                time.sleep(wait)
            self._last_books_request_at = time.monotonic()
            try:
                return operation(*args)
            except Exception as exc:
                if "code=44" not in str(exc) or attempt == 3:
                    raise
                time.sleep(65)

    def run(self) -> BackfillResult:
        records = self.creator.get_all_records(
            self.config.creator_app, self.config.creator_report
        )
        dates = [date for row in records if (date := parse_date(row.get("Payment_Date")))]
        if not dates:
            raise ValueError("Creator matched payments have no valid payment date.")
        oldest_date = min(dates)
        crosscheck = self.creator.get_all_records(
            self.config.creator_app, self.config.creator_crosscheck_report
        )
        canonical_by_id = {
            to_text(row.get("ID")): row for row in crosscheck if to_text(row.get("ID"))
        }
        sequence_gaps = find_creator_sequence_gaps(records, crosscheck)
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
        payments = [
            payment for payment in self.books.customer_payments.list_all()
            if to_text(payment.get("location_id")) == self.config.location_id
            and (payment_date := parse_date(payment.get("date"))) is not None
            and payment_date >= oldest_date
        ]
        by_id, by_number = build_native_payment_indexes(payments)
        claims: Dict[str, set[str]] = {}
        for record in [*crosscheck, *records]:
            candidate, _ = resolve_books_payment(
                _crosschecked_values(
                    record, canonical_by_id.get(to_text(record.get("ID")))
                ), payments, by_id, by_number
            )
            record_id = to_text(record.get("ID"))
            if candidate is not None and record_id:
                payment_id = to_text(candidate.get("payment_id") or candidate.get("id"))
                claims.setdefault(payment_id, set()).add(record_id)
        rows: List[Dict[str, Any]] = []
        details: Dict[str, Mapping[str, Any]] = {}
        missing_link_ids: set[str] = set()
        for payment in payments:
            payment_id = to_text(payment.get("payment_id") or payment.get("id"))
            if not payment_id:
                continue
            details[payment_id] = payment
            values = _custom_field_values(payment)
            if not values.get("cf_creator_record_id") or not values.get("cf_creator_payment_id"):
                missing_link_ids.add(payment_id)
        matched_payment_ids: set[str] = set()
        for record in records:
            record_id = to_text(record.get("ID"))
            if record_id in resumed and resumed[record_id].get("status") == "updated":
                payment, _ = resolve_books_payment(
                    _crosschecked_values(record, canonical_by_id.get(record_id)),
                    payments, by_id, by_number
                )
                if payment is not None:
                    matched_payment_ids.add(to_text(payment.get("payment_id") or payment.get("id")))
                rows.append(resumed[record_id])
                continue
            creator_payment_id = to_text(record.get("Payment_ID"))
            if not record_id or not creator_payment_id:
                rows.append({
                    "creator_record_id": record_id,
                    "status": "creator_data_incomplete",
                })
                _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
                continue
            payment, source = resolve_books_payment(
                _crosschecked_values(record, canonical_by_id.get(record_id)),
                payments, by_id, by_number
            )
            row: Dict[str, Any] = {
                "creator_record_id": record_id,
                "match_source": source,
            }
            if payment is None:
                row["status"] = source
            else:
                row["books_payment_id"] = to_text(
                    payment.get("payment_id") or payment.get("id")
                )
                if not row["books_payment_id"]:
                    row["status"] = "payment_missing"
                    rows.append(row)
                    _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
                    continue
                matched_payment_ids.add(row["books_payment_id"])
                if len(claims.get(row["books_payment_id"], set())) > 1:
                    row["status"] = "creator_match_ambiguous"
                    rows.append(row)
                    _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
                    continue
                current = details.get(row["books_payment_id"])
                if current is None:
                    row["status"] = "payment_read_failed"
                    rows.append(row)
                    _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
                    continue
                status, _missing = classify_links(current, record_id, creator_payment_id)
                if status == "ready" and self.config.execute:
                    try:
                        current = unwrap_record(
                            self._books_request(
                                self.books.customer_payments.get,
                                row["books_payment_id"],
                            ),
                            ("customerpayment", "customer_payment", "payment"),
                        )
                        if not isinstance(current, Mapping):
                            raise RuntimeError("Books returned no customer payment record.")
                        if (to_text(current.get("location_id")) != self.config.location_id
                                or (payment_date := parse_date(current.get("date"))) is None
                                or payment_date < oldest_date):
                            raise RuntimeError("Books payment is outside the requested date or location.")
                        status, _missing = classify_links(current, record_id, creator_payment_id)
                        if status != "ready":
                            row["status"] = status
                            rows.append(row)
                            _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
                            continue
                        response = self._books_request(
                            self.books.customer_payments.update,
                            row["books_payment_id"],
                            {
                                "custom_fields": [
                                    {"label": "Creator Record ID", "value": record_id},
                                    {"label": "Creator Payment ID", "value": creator_payment_id},
                                ]
                            },
                        )
                        if not isinstance(response, Mapping) or str(
                            response.get("code", "")
                        ).strip() not in {"0"}:
                            raise RuntimeError("Books rejected the custom-field update.")
                        verified = unwrap_record(
                            self._books_request(
                                self.books.customer_payments.get,
                                row["books_payment_id"],
                            ),
                            ("customerpayment", "customer_payment", "payment"),
                        )
                        verified_status, _ = classify_links(
                            verified, record_id, creator_payment_id
                        )
                        if verified_status != "already_linked":
                            raise RuntimeError("Books custom-field verification failed.")
                        row["status"] = "updated"
                    except Exception as exc:
                        if "code=44" in str(exc):
                            raise
                        row["status"] = "update_failed"
                        row["error"] = str(exc)
                else:
                    row["status"] = status
            rows.append(row)
            _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
        for payment_id in sorted(missing_link_ids - matched_payment_ids):
            payment = by_id[payment_id]
            owners = sorted(claims.get(payment_id, set()))
            rows.append({
                "books_payment_id": payment_id,
                "payment_number": to_text(payment.get("payment_number")),
                "creator_crosscheck_ids": owners,
                "status": "creator_crosscheck_found" if len(owners) == 1
                else "creator_crosscheck_ambiguous" if owners
                else "creator_crosscheck_missing",
            })
            _write_checkpoint(self.config.checkpoint_path, BackfillResult(rows, oldest_date.isoformat(), sequence_gaps))
        result = BackfillResult(rows, oldest_date.isoformat(), sequence_gaps)
        _write_checkpoint(self.config.checkpoint_path, result)
        return result

