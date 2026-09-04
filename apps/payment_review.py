#!/usr/bin/env python3
"""Serve a local accept/reject queue for Creator Online and Cheque payment matches."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import unquote, urlparse

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.collection_reconciliation import (
    OnlinePaymentReviewConfig,
    OnlinePaymentReviewService,
)
from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.config import Config

_TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "payment_review.html"
HTML = _TEMPLATE_PATH.read_text(encoding="utf-8")


def _clients(token_url: str, owner: Optional[str], org_id: str, domain: str):
    creator = get_creator_client(owner_name=owner, domain=domain, token_url=token_url)
    books = get_books_client(org_id=org_id, domain=domain, token_url=token_url)
    return creator, books


def make_handler(service: OnlinePaymentReviewService, review_token: str):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, value: Any, status: int = 200) -> None:
            payload = json.dumps(value, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            return secrets.compare_digest(
                self.headers.get("X-Review-Token", ""), review_token
            )

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                payload = HTML.replace("__TOKEN__", review_token).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
                )
                self.end_headers()
                self.wfile.write(payload)
            elif path == "/api/batch" and self._authorized():
                self._json(service.load())
            else:
                self._json({"error": "Not found"}, 404)

        def do_POST(self) -> None:
            if not self._authorized():
                self._json({"error": "Invalid review token"}, 403)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if body.get("confirm") is not True:
                    raise ValueError("Explicit confirmation is required.")
                path = urlparse(self.path).path
                if path == "/api/refresh":
                    self._json(service.refresh())
                    return
                if path == "/api/accept-selected":
                    entry_ids = body.get("entry_ids")
                    if not isinstance(entry_ids, list):
                        raise ValueError("entry_ids must be a list.")
                    selected_bank_transaction_ids = body.get(
                        "selected_bank_transaction_ids", {}
                    )
                    if not isinstance(selected_bank_transaction_ids, dict):
                        raise ValueError(
                            "selected_bank_transaction_ids must be an object."
                        )
                    self._json(
                        service.accept_many(
                            entry_ids,
                            selected_bank_transaction_ids,
                            allow_reference_override=bool(
                                body.get("allow_reference_override")
                            ),
                        )
                    )
                    return
                prefix = "/api/entries/"
                if not path.startswith(prefix):
                    raise ValueError("Unknown action.")
                remainder = path[len(prefix):]
                entry_id, action = remainder.rsplit("/", 1)
                entry_id = unquote(entry_id)
                if action == "reject":
                    self._json(service.reject(entry_id))
                elif action == "accept":
                    self._json(
                        service.accept_and_push(
                            entry_id,
                            selected_bank_transaction_id=str(
                                body.get("bank_transaction_id") or ""
                            ),
                            allow_reference_override=bool(
                                body.get("allow_reference_override")
                            ),
                        )
                    )
                else:
                    raise ValueError("Unknown action.")
            except Exception as exc:
                logging.exception("Review action failed")
                self._json({"error": str(exc)}, 400)

        def log_message(self, format: str, *args: Any) -> None:
            logging.info("Review UI: " + format, *args)

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--creator-owner", default=Config.CREATOR_OWNER_NAME or None)
    parser.add_argument(
        "--bank-account-id",
        help="Use one Books bank account instead of the default HDFC/ICICI/IDFC set",
    )
    parser.add_argument("--token-url", default=Config.TOKEN_URL)
    parser.add_argument("--org-id", default=Config.ORG_ID)
    parser.add_argument("--domain", default=Config.DOMAIN)
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("output/collection_reconciliation/online_payments_review.json"),
    )
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument(
        "--refresh-only",
        action="store_true",
        help="Refresh the read-only reconciliation preview and exit without serving the UI.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("The review server may only bind to a loopback address.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    creator, books = _clients(args.token_url, args.creator_owner, args.org_id, args.domain)
    bank_accounts = (
        (("Bank", args.bank_account_id),)
        if args.bank_account_id
        else (
            ("HDFC", Config.BANK_ACCOUNT_HDFC),
            ("ICICI", Config.BANK_ACCOUNT_ICICI),
            ("IDFC", Config.BANK_ACCOUNT_IDFC),
        )
    )
    service = OnlinePaymentReviewService(
        creator,
        books,
        OnlinePaymentReviewConfig(
            creator_app_link_name=args.creator_app,
            bank_accounts=bank_accounts,
            payment_reports=(
                ("Online", Config.PAYMENT_CREATOR_REPORTS["online"]),
                ("Cheque", Config.PAYMENT_CREATOR_REPORTS["cheque"]),
            ),
            cheque_detail_report_link_name=Config.PAYMENT_CREATOR_REPORTS[
                "cheque_detail"
            ],
            customer_report_link_name=Config.PAYMENT_CREATOR_REPORTS["customer"],
            creator_checkpoint_report_link_name=Config.PAYMENT_CREATOR_REPORTS[
                "checkpoint"
            ],
            state_path=args.state,
        ),
    )
    if not args.no_refresh or not args.state.exists():
        batch = service.refresh()
        logging.info("Loaded %s Creator payment review entries", len(batch["entries"]))
    else:
        batch = service.load()
    if args.refresh_only:
        entries = batch.get("entries", [])
        in_progress = {
            "payment_created",
            "match_requested",
            "bank_matched",
            "creator_updated",
        }
        ready = sum(
            1
            for entry in entries
            if entry.get("reviewable")
            and entry.get("push_status") != "pushed"
            and entry.get("push_status") not in in_progress
        )
        print(
            json.dumps(
                {
                    "entries": len(entries),
                    "ready": ready,
                    "state": str(args.state),
                },
                indent=2,
            ),
            flush=True,
        )
        return 0
    review_token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service, review_token))
    print(f"Review UI: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
