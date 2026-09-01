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


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="launcher-token" content="__TOKEN__"><title>Zoho SDK Operations</title>
<style>
:root{color-scheme:dark;--bg:#07110f;--panel:#0d1a17;--panel2:#10221d;--ink:#ecf7f2;--muted:#92aaa1;--line:#203a32;--mint:#72f0b6;--amber:#ffc66d;--red:#ff8178}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#12392f 0,transparent 32rem),var(--bg);color:var(--ink);font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}main{width:min(1180px,calc(100% - 32px));margin:auto;padding:54px 0 70px}header{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;margin-bottom:34px}.eyebrow{color:var(--mint);letter-spacing:.14em;text-transform:uppercase;font-size:12px}h1{font:700 clamp(34px,6vw,68px)/.98 ui-sans-serif,system-ui;margin:9px 0 13px;letter-spacing:-.05em;max-width:720px}header p{color:var(--muted);max-width:670px;margin:0}.pulse{display:flex;align-items:center;gap:8px;color:var(--mint);font-size:13px}.pulse:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 18px var(--mint)}.callbox{display:grid;grid-template-columns:1fr auto;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:24px;box-shadow:0 18px 70px #0005}.callbox input{min-width:0;border:0;outline:0;background:transparent;color:var(--ink);font:600 18px ui-monospace,SFMono-Regular,Menlo,monospace;padding:8px 10px}.callbox input::placeholder{color:#678077}.callbox button,.run{border:0;border-radius:10px;background:var(--mint);color:#052117;font-weight:800;padding:11px 18px;cursor:pointer}.callbox button:disabled,.run:disabled{opacity:.4;cursor:not-allowed}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{position:relative;display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:start;background:linear-gradient(150deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:19px;min-height:148px;transition:.18s transform,.18s border-color}.card:hover{transform:translateY(-2px);border-color:#3b6f5f}.num{display:grid;place-items:center;width:46px;height:46px;border:1px solid #376052;border-radius:12px;color:var(--mint);font-size:20px;font-weight:800}.card h2{font:700 18px/1.25 ui-sans-serif,system-ui;margin:1px 0 7px}.card p{color:var(--muted);margin:0 0 16px;font-size:13px}.meta{display:flex;gap:8px;flex-wrap:wrap}.tag{border:1px solid var(--line);border-radius:999px;padding:3px 8px;color:#b6cbc3;font-size:11px}.status{grid-column:2/-1;color:var(--muted);font-size:12px;white-space:pre-wrap}.status.running{color:var(--amber)}.status.succeeded{color:var(--mint)}.status.failed{color:var(--red)}.open{color:var(--mint);margin-left:8px}.console{margin-top:24px;background:#030807;border:1px solid var(--line);border-radius:16px;overflow:hidden}.console-head{display:flex;justify-content:space-between;padding:12px 16px;background:#0b1512;color:var(--muted);font-size:12px}.console pre{margin:0;padding:18px;min-height:150px;max-height:340px;overflow:auto;color:#c5d8d1;white-space:pre-wrap;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}@media(max-width:760px){main{padding-top:30px}header{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.card{grid-template-columns:auto 1fr}.run{grid-column:1/-1}.status{grid-column:1/-1}}
</style></head><body><main><header><div><div class="eyebrow">Local operations desk</div><h1>Choose a workflow. Keep the context.</h1><p>Frequently used Zoho jobs are numbered, allowlisted, and launched from this machine. Type a number and press Enter, or use a card.</p></div><div class="pulse">Launcher online</div></header>
<section class="callbox"><input id="call" inputmode="numeric" autocomplete="off" aria-label="Workflow number" placeholder="Call workflow number…"><button id="callButton">Run</button></section><section class="grid" id="grid"></section>
<section class="console"><div class="console-head"><span id="consoleTitle">Run output</span><span id="consoleState">Waiting</span></div><pre id="logs">Select a workflow to see its output here.</pre></section></main>
<script>
const token=document.querySelector('meta[name="launcher-token"]').content;let state={workflows:[],runs:[]},selectedRun=null;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function latest(number){return [...state.runs].reverse().find(r=>r.workflow_number===number)}
function render(){document.getElementById('grid').innerHTML=state.workflows.map(w=>{const r=latest(w.number),busy=r&&['starting','running'].includes(r.status);return `<article class="card"><div class="num">${w.number}</div><div><h2>${esc(w.name)}</h2><p>${esc(w.description)}</p><div class="meta"><span class="tag">${esc(w.category)}</span><span class="tag">${esc(w.safety)}</span></div></div><button class="run" ${busy?'disabled':''} onclick="run(${w.number})">${busy?'Running':'Run '+w.number}</button><div class="status ${esc(r?.status||'')}">${r?esc(r.status):'Not run yet'}${r?.open_url&&busy?` · <a class="open" href="${esc(r.open_url)}" target="_blank">Open UI ↗</a>`:''}</div></article>`}).join('');showConsole()}
function showConsole(){const r=state.runs.find(x=>x.run_id===selectedRun)||state.runs.at(-1);if(!r)return;selectedRun=r.run_id;document.getElementById('consoleTitle').textContent=`Run ${r.run_id} · ${r.name}`;document.getElementById('consoleState').textContent=r.status;const pre=document.getElementById('logs');pre.textContent=(r.logs||[]).join('\n')||'Process started. Waiting for output…';pre.scrollTop=pre.scrollHeight}
async function refresh(){const response=await fetch('/api/state',{cache:'no-store'});state=await response.json();render()}
async function run(number){const response=await fetch('/api/workflows/'+number+'/run',{method:'POST',headers:{'Content-Type':'application/json','X-Launcher-Token':token},body:JSON.stringify({confirm:true})});const data=await response.json();if(!response.ok){alert(data.error||'Unable to start workflow');return}selectedRun=data.run_id;await refresh();if(data.open_url)setTimeout(()=>window.open(data.open_url,'_blank'),700)}
function call(){const number=Number(document.getElementById('call').value);if(!state.workflows.some(w=>w.number===number)){alert('Enter a workflow number shown below.');return}run(number)}
document.getElementById('callButton').onclick=call;document.getElementById('call').addEventListener('keydown',e=>{if(e.key==='Enter')call()});refresh();setInterval(refresh,1500);
</script></body></html>"""


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
