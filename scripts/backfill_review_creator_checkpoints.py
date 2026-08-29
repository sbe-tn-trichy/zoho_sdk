#!/usr/bin/env python3
"""Backfill Creator Books checkpoint fields for review-tool payments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from workflows.collection_reconciliation.review import OnlinePaymentReviewService
from workflows.core.config import Config
from zoho import HttpTokenProvider, ZohoBooksAPI, ZohoCreatorAPI


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identifier(payload: Any, key: str) -> str:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list)):
            return str(value)
        for nested in payload.values():
            found = _identifier(nested, key)
            if found:
                return found
    elif isinstance(payload, list):
        for nested in payload:
            found = _identifier(nested, key)
            if found:
                return found
    return ""


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _creator_record(creator: Any, app: str, record_id: str) -> Mapping[str, Any]:
    response = creator.get_records(
        app,
        "All_Payments",
        params={"criteria": f"ID == {record_id}", "field_config": "all"},
    )
    rows = response.get("data", []) if isinstance(response, Mapping) else []
    return next(
        (
            row
            for row in rows
            if isinstance(row, Mapping) and _text(row.get("ID")) == record_id
        ),
        {},
    )


def backfill(
    state_path: Path,
    checkpoint_path: Path,
    creator: Any,
    books: Any,
    creator_app: str,
    execute: bool,
    max_writes: int,
) -> Dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = {}
    if checkpoint_path.exists():
        old = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        previous = {
            _text(row.get("record_id")): row
            for row in old.get("rows", [])
            if _text(row.get("status")) in {"updated", "already_current"}
        }

    rows = []
    writes = 0
    entries = [entry for entry in state.get("entries", []) if _text(entry.get("books_payment_id"))]
    for entry in entries:
        record_id = _text(entry.get("id"))
        books_payment_id = _text(entry.get("books_payment_id"))
        if record_id in previous:
            rows.append(previous[record_id])
            continue
        result: Dict[str, Any] = {
            "record_id": record_id,
            "reference": _text(entry.get("creator", {}).get("reference")),
            "books_payment_id": books_payment_id,
        }
        try:
            payment_response = books.customer_payments.get(books_payment_id)
            payment_number = _identifier(payment_response, "payment_number")
            if not payment_number:
                raise ValueError("Books returned no payment_number")
            result["books_payment_number"] = payment_number
            current = _creator_record(creator, creator_app, record_id)
            if not current:
                raise ValueError("Creator record was not found in All_Payments")
            expected = {
                "Books_Transaction_Id": books_payment_id,
                "PaymentNo": payment_number,
            }
            if all(_text(current.get(key)) == value for key, value in expected.items()):
                result["status"] = "already_current"
            elif not execute:
                result["status"] = "planned"
                result["current"] = {
                    key: _text(current.get(key)) for key in expected
                }
            elif max_writes and writes >= max_writes:
                result["status"] = "write_limit"
            else:
                response = creator.update_records(
                    creator_app,
                    "All_Payments",
                    {"data": expected},
                    record_id=record_id,
                )
                OnlinePaymentReviewService._require_creator_update_success(response)
                verified = _creator_record(creator, creator_app, record_id)
                if not all(_text(verified.get(key)) == value for key, value in expected.items()):
                    raise ValueError("Creator read-back verification failed")
                entry["books_payment_number"] = payment_number
                result["status"] = "updated"
                writes += 1
                _atomic_json(state_path, state)
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
        rows.append(result)
        checkpoint = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "execute": execute,
            "rows": rows,
        }
        _atomic_json(checkpoint_path, checkpoint)

    summary: Dict[str, int] = {"total": len(rows), "writes": writes}
    for row in rows:
        status = _text(row.get("status")) or "unknown"
        summary[status] = summary.get(status, 0) + 1
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "execute": execute,
        "summary": summary,
        "rows": rows,
    }
    _atomic_json(checkpoint_path, payload)
    return payload


def _clients(token_url: str, owner: str, org_id: str, domain: str):
    provider = HttpTokenProvider(token_url, timeout=30)

    def token_for(primary: str, fallback: str) -> str:
        tokens = provider.get_tokens()
        return tokens.get(primary) or tokens.get(fallback) or ""

    tokens = provider.get_tokens()
    creator = ZohoCreatorAPI(
        access_token=tokens.get("creator") or tokens.get("zoho_creator_conn") or "",
        account_owner_name=owner,
        domain=domain,
        send_environment_header=False,
        token_refresh_callback=lambda: token_for("creator", "zoho_creator_conn"),
    )
    books = ZohoBooksAPI(
        access_token=tokens.get("books") or tokens.get("zoho_books_conn") or "",
        organization_id=org_id,
        domain=domain,
        token_refresh_callback=lambda: token_for("books", "zoho_books_conn"),
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
        "--state",
        type=Path,
        default=Path("output/collection_reconciliation/online_payments_review.json"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("output/collection_reconciliation/creator_checkpoint_backfill.json"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_writes < 0:
        raise SystemExit("--max-writes cannot be negative")
    creator, books = _clients(args.token_url, args.creator_owner, args.org_id, args.domain)
    result = backfill(
        args.state,
        args.checkpoint,
        creator,
        books,
        args.creator_app,
        args.execute,
        args.max_writes,
    )
    print(json.dumps(result["summary"], indent=2))
    print(f"Checkpoint: {args.checkpoint}")
    return 1 if result["summary"].get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
