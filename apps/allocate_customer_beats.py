#!/usr/bin/env python3
"""Serve a local review page for assigning jurisdiction-matched Creator beats."""

from __future__ import annotations

import argparse
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.core.config import Config
from workflows.core.exceptions import ReconciliationError
from workflows.creator_beat_allocation import CreatorBeatAllocationService


HTML_PATH = Path(__file__).parent / "static" / "customer_beat_allocation.html"


def make_handler(service: CreatorBeatAllocationService, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, value: Any) -> None:
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed_host(self) -> bool:
            return self.headers.get("Host") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def do_GET(self) -> None:
            if not self._allowed_host():
                self.send_error(403)
                return
            if self.path == "/":
                body = HTML_PATH.read_text(encoding="utf-8").replace("__CSRF_TOKEN__", token).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/customers":
                try:
                    rows = service.list_unallocated()
                    self._json(200, {"customers": rows})
                except Exception as exc:
                    self._json(502, {"error": str(exc)})
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if not self._allowed_host() or not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), token
            ):
                self.send_error(403)
                return
            if self.path != "/api/allocate":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2048:
                    raise ValueError("Invalid request length")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                result = service.allocate(
                    data.get("creator_id", ""), data.get("books_id", ""), data.get("beat_id", "")
                )
                self._json(200, result)
            except (ValueError, ReconciliationError) as exc:
                self._json(409, {"error": str(exc)})
            except Exception as exc:
                self._json(502, {"error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    service = CreatorBeatAllocationService(
        get_books_client(), get_creator_client(), Config.PAYMENT_CREATOR_APP_LINK_NAME,
        Config.PAYMENT_CREATOR_REPORTS.get("customer", "All_Customers1"),
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, secrets.token_urlsafe(32)))
    print(f"Beat allocation UI: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
