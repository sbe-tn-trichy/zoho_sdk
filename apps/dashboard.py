#!/usr/bin/env python3
"""Serve a loopback-only launcher for frequently used project workflows."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_LOG_LINES = 400


@dataclass(frozen=True)
class WorkflowSpec:
    number: int
    name: str
    description: str
    command: tuple[str, ...]
    category: str
    safety: str = "Read-only"
    open_url: Optional[str] = None


WORKFLOWS = (
    WorkflowSpec(
        1,
        "Payment reconciliation",
        "Open the human review queue for online and cheque payments.",
        (sys.executable, "apps/payment_review.py"),
        "Collections",
        "Review required",
        "http://127.0.0.1:8765",
    ),
    WorkflowSpec(
        2,
        "Payment reconciliation preview",
        "Refresh production online and cheque payment matches without writing to Zoho.",
        (sys.executable, "apps/payment_review.py", "--refresh-only"),
        "Collections",
    ),
    WorkflowSpec(
        3,
        "Duplicate customer payments",
        "Scan Books and create a searchable local HTML report.",
        (
            sys.executable,
            "apps/check_duplicate_payments.py",
            "--output",
            "output/duplicate_customer_payments.html",
        ),
        "Audit",
    ),
    WorkflowSpec(
        4,
        "Export ICICI unmatched entries",
        "Download uncategorized ICICI bank transactions to an audit CSV.",
        (sys.executable, "apps/export_icici_unmatched.py"),
        "Banking",
    ),
    WorkflowSpec(
        5,
        "Collection reconciliation run",
        "Run single-step automated collection reconciliation against Books.",
        (sys.executable, "apps/run_collection_reconciliation.py"),
        "Collections",
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRunner:
    """Run only commands from the fixed workflow registry."""

    def __init__(
        self,
        repo_root: Path = PROJECT_ROOT,
        workflows: Sequence[WorkflowSpec] = WORKFLOWS,
    ) -> None:
        self.repo_root = repo_root
        self.workflows = {item.number: item for item in workflows}
        self._runs: dict[int, dict[str, Any]] = {}
        self._processes: dict[int, subprocess.Popen[str]] = {}
        self._next_run_id = 1
        self._lock = threading.Lock()

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {
                "number": item.number,
                "name": item.name,
                "description": item.description,
                "category": item.category,
                "safety": item.safety,
                "open_url": item.open_url,
                "command": " ".join(Path(part).name if i == 0 else part for i, part in enumerate(item.command)),
            }
            for item in self.workflows.values()
        ]

    def start(self, number: int) -> dict[str, Any]:
        spec = self.workflows.get(number)
        if spec is None:
            raise ValueError(f"Unknown workflow number: {number}")

        with self._lock:
            for run_id, process in self._processes.items():
                run = self._runs[run_id]
                if run["workflow_number"] == number and process.poll() is None:
                    return dict(run)

            run_id = self._next_run_id
            self._next_run_id += 1
            run = {
                "run_id": run_id,
                "workflow_number": number,
                "name": spec.name,
                "status": "starting",
                "started_at": _now(),
                "finished_at": None,
                "exit_code": None,
                "logs": [],
                "open_url": spec.open_url,
            }
            self._runs[run_id] = run

        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(
                spec.command,
                cwd=self.repo_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except Exception as exc:
            with self._lock:
                run.update(
                    status="failed",
                    finished_at=_now(),
                    logs=[f"Could not start: {exc}"],
                )
            return dict(run)

        with self._lock:
            self._processes[run_id] = process
            run["status"] = "running"
        threading.Thread(target=self._capture, args=(run_id, process), daemon=True).start()
        return self.get(run_id)

    def _capture(self, run_id: int, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            with self._lock:
                logs = self._runs[run_id]["logs"]
                logs.append(line.rstrip())
                del logs[:-MAX_LOG_LINES]
        exit_code = process.wait()
        with self._lock:
            run = self._runs[run_id]
            run["exit_code"] = exit_code
            run["finished_at"] = _now()
            run["status"] = "succeeded" if exit_code == 0 else "failed"

    def get(self, run_id: int) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"Unknown run: {run_id}")
            return {**run, "logs": list(run["logs"])}

    def state(self) -> dict[str, Any]:
        with self._lock:
            runs = [{**run, "logs": list(run["logs"])} for run in self._runs.values()]
        return {"workflows": self.list_workflows(), "runs": runs}


_TEMPLATE_PATH = Path(__file__).resolve().parent / "static" / "dashboard.html"
HTML = _TEMPLATE_PATH.read_text(encoding="utf-8")


def make_handler(runner: WorkflowRunner, launcher_token: str):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, value: Any, status: int = 200) -> None:
            payload = json.dumps(value, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                payload = HTML.replace("__TOKEN__", launcher_token).encode("utf-8")
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
            elif path == "/api/state":
                self._json(runner.state())
            else:
                self._json({"error": "Not found"}, 404)

        def do_POST(self) -> None:
            if not secrets.compare_digest(
                self.headers.get("X-Launcher-Token", ""), launcher_token
            ):
                self._json({"error": "Invalid launcher token"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = json.loads(self.rfile.read(length) or b"{}")
                if body.get("confirm") is not True:
                    raise ValueError("Explicit confirmation is required.")
                parts = urlparse(self.path).path.strip("/").split("/")
                if len(parts) != 4 or parts[:2] != ["api", "workflows"] or parts[3] != "run":
                    raise ValueError("Unknown action.")
                self._json(runner.start(int(parts[2])))
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8750)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("The project dashboard may only bind to a loopback address.")
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(WorkflowRunner(), token))
    print(f"Project dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
