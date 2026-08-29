#!/usr/bin/env python3
"""Match Creator Online_Payments to Books and backfill Creator checkpoint fields."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from workflows.collection_reconciliation.review import OnlinePaymentReviewService
from workflows.core.config import Config
from workflows.core.matching import parse_date
from zoho import HttpTokenProvider, ZohoBooksAPI, ZohoCreatorAPI


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return "".join(char for char in _text(value).casefold() if char.isalnum())


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(_text(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_customer_map(rows: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    return {
        _text(row.get("ID")): _text(row.get("Customer_Id"))
        for row in rows
        if _text(row.get("ID")) and _text(row.get("Customer_Id"))
    }


def creator_values(record: Mapping[str, Any], customers: Mapping[str, str]) -> Dict[str, Any]:
    lookup = record.get("Customer_Name")
    lookup = lookup if isinstance(lookup, Mapping) else {}
    return {
        "record_id": _text(record.get("ID")),
        "date": parse_date(record.get("Payment_Date")),
        "amount": _decimal(record.get("Payment_Amount")),
        "reference": _text(record.get("Reference")),
        "customer_id": customers.get(_text(lookup.get("ID")), ""),
        "books_payment_id": _text(record.get("Books_Transaction_Id")),
        "books_payment_number": _text(record.get("PaymentNo")),
    }


def find_books_payment(
    values: Mapping[str, Any],
    payments: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[Mapping[str, Any]], str]:
    existing_id = _text(values.get("books_payment_id"))
    existing_number = _norm(values.get("books_payment_number"))
    direct = [
        row
        for row in payments
        if (existing_id and _text(row.get("payment_id")) == existing_id)
        or (existing_number and _norm(row.get("payment_number")) == existing_number)
    ]
    direct_ids = {_text(row.get("payment_id")) for row in direct if _text(row.get("payment_id"))}
    if len(direct_ids) == 1:
        return direct[0], "existing_identifier"
    if len(direct_ids) > 1:
        return None, "identifier_conflict"

    if not all(
        (
            values.get("date"),
            values.get("amount") is not None,
            _norm(values.get("reference")),
            _text(values.get("customer_id")),
        )
    ):
        return None, "creator_data_incomplete"
    candidates = []
    for payment in payments:
        if _text(payment.get("customer_id")) != _text(values.get("customer_id")):
            continue
        if parse_date(payment.get("date")) != values.get("date"):
            continue
        amount = _decimal(payment.get("amount"))
        if amount is None or abs(amount) != abs(values["amount"]):
            continue
        if _norm(payment.get("reference_number")) != _norm(values.get("reference")):
            continue
        candidates.append(payment)
    unique = {
        _text(row.get("payment_id")): row
        for row in candidates
        if _text(row.get("payment_id"))
    }
    if len(unique) == 1:
        return next(iter(unique.values())), "exact_customer_date_amount_reference"
    if len(unique) > 1:
        return None, "payment_ambiguous"
    return None, "payment_missing"


def _creator_record(creator: Any, app: str, record_id: str) -> Mapping[str, Any]:
    response = creator.get_records(
        app,
        "All_Payments",
        params={"criteria": f"ID == {record_id}", "field_config": "all"},
    )


def _all_creator_records(creator: Any, app: str, report: str) -> List[Mapping[str, Any]]:
    rows: List[Mapping[str, Any]] = []
    response = creator.get_records(
        app,
        report,
        params={"max_records": 1000, "field_config": "all"},
    )
    seen_cursors = set()
    while True:
        rows.extend(
            row for row in response.get("data", []) if isinstance(row, Mapping)
        )
        context = response.get("page_context", {})
        if context.get("has_more_page") is False:
            break
        cursor = context.get("record_cursor") or response.get("record_cursor")
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        response = creator.get_records(
            app,
            report,
            params={"field_config": "all"},
            headers={"record_cursor": cursor},
        )
    return rows
    rows = response.get("data", []) if isinstance(response, Mapping) else []
    return next(
        (
            row
            for row in rows
            if isinstance(row, Mapping) and _text(row.get("ID")) == record_id
        ),
        {},
    )


def run_backfill(
    creator: Any,
    books: Any,
    creator_app: str,
    execute: bool,
    max_writes: int,
    checkpoint_path: Path,
) -> Dict[str, Any]:
    visible_rows = creator.get_all_records(creator_app, "Online_Payments")
    canonical_rows = _all_creator_records(creator, creator_app, "All_Payments")
    canonical_by_id = {
        _text(row.get("ID")): row for row in canonical_rows if _text(row.get("ID"))
    }
    creator_rows = [
        {**visible, **canonical_by_id.get(_text(visible.get("ID")), {})}
        for visible in visible_rows
    ]
    customer_rows = creator.get_all_records(creator_app, "All_Customers1")
    customers = build_customer_map(customer_rows)
    payments = books.customer_payments.list_all()
    payment_id_owners = {
        _text(row.get("Books_Transaction_Id")): _text(row.get("ID"))
        for row in canonical_rows
        if _text(row.get("Books_Transaction_Id"))
    }
    payment_number_owners = {
        _norm(row.get("PaymentNo")): _text(row.get("ID"))
        for row in canonical_rows
        if _norm(row.get("PaymentNo"))
    }
    results: List[Dict[str, Any]] = []
    writes = 0

    for record in creator_rows:
        values = creator_values(record, customers)
        result = {
            "record_id": values["record_id"],
            "reference": values["reference"],
        }
        payment, source = find_books_payment(values, payments)
        result["match_source"] = source
        if not payment:
            result["status"] = source
        else:
            payment_id = _text(payment.get("payment_id"))
            payment_number = _text(payment.get("payment_number"))
            result.update(
                books_payment_id=payment_id,
                books_payment_number=payment_number,
            )
            id_owner = payment_id_owners.get(payment_id)
            number_owner = payment_number_owners.get(_norm(payment_number))
            conflicting_owners = {
                owner
                for owner in (id_owner, number_owner)
                if owner and owner != values["record_id"]
            }
            if conflicting_owners:
                result["status"] = "books_payment_already_linked"
                result["linked_creator_record_ids"] = sorted(conflicting_owners)
            elif not payment_id or not payment_number:
                result["status"] = "books_identifiers_incomplete"
            elif (
                values["books_payment_id"] == payment_id
                and values["books_payment_number"] == payment_number
            ):
                result["status"] = "already_current"
            elif not execute:
                result["status"] = "planned"
            elif max_writes and writes >= max_writes:
                result["status"] = "write_limit"
            else:
                try:
                    expected = {
                        "Books_Transaction_Id": payment_id,
                        "PaymentNo": payment_number,
                    }
                    response = creator.update_records(
                        creator_app,
                        "All_Payments",
                        {"data": expected},
                        record_id=values["record_id"],
                    )
                    OnlinePaymentReviewService._require_creator_update_success(response)
                    verified = _creator_record(creator, creator_app, values["record_id"])
                    if not all(_text(verified.get(key)) == value for key, value in expected.items()):
                        raise ValueError("Creator read-back verification failed")
                    writes += 1
                    result["status"] = "updated"
                except Exception as exc:
                    result["status"] = "failed"
                    result["error"] = str(exc)
        results.append(result)
        _atomic_json(
            checkpoint_path,
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "execute": execute,
                "rows": results,
            },
        )

    summary: Dict[str, int] = {"total": len(results), "writes": writes}
    for row in results:
        status = _text(row.get("status")) or "unknown"
        summary[status] = summary.get(status, 0) + 1
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "execute": execute,
        "summary": summary,
        "rows": results,
    }
    _atomic_json(checkpoint_path, payload)
    return payload


def _clients(token_url: str, owner: str, org_id: str, domain: str):
    provider = HttpTokenProvider(token_url, timeout=30)
    tokens = provider.get_tokens()
    creator = ZohoCreatorAPI(
        access_token=tokens.get("creator") or tokens.get("zoho_creator_conn") or "",
        account_owner_name=owner,
        domain=domain,
        send_environment_header=False,
    )
    books = ZohoBooksAPI(
        access_token=tokens.get("books") or tokens.get("zoho_books_conn") or "",
        organization_id=org_id,
        domain=domain,
    )
    return creator, books


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-writes", type=int, default=10, help="0 means unlimited")
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--creator-owner", default="bharathdst")
    parser.add_argument("--token-url", default=Config.TOKEN_URL)
    parser.add_argument("--org-id", default=Config.ORG_ID)
    parser.add_argument("--domain", default=Config.DOMAIN)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("output/collection_reconciliation/online_payment_books_backfill.json"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_writes < 0:
        raise SystemExit("--max-writes cannot be negative")
    creator, books = _clients(args.token_url, args.creator_owner, args.org_id, args.domain)
    result = run_backfill(
        creator,
        books,
        args.creator_app,
        args.execute,
        args.max_writes,
        args.checkpoint,
    )
    print(json.dumps(result["summary"], indent=2))
    print(f"Checkpoint: {args.checkpoint}")
    return 1 if result["summary"].get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
