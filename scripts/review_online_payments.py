#!/usr/bin/env python3
"""Serve a local accept/reject queue for Creator Online_Payments matches."""

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

from workflows.collection_reconciliation import (
    OnlinePaymentReviewConfig,
    OnlinePaymentReviewService,
)
from workflows.core.config import Config
from zoho import HttpTokenProvider, ZohoBooksAPI, ZohoCreatorAPI


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="review-token" content="__TOKEN__">
  <title>Online Payment Reconciliation</title>
  <style>
    :root { color-scheme: light; --ink:#14213d; --muted:#64748b; --line:#dbe3ed;
      --paper:#fff; --bg:#f3f6fa; --blue:#155eef; --green:#087443; --red:#b42318; }
    * { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--ink);
      font:14px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }
    header { position:sticky; top:0; z-index:2; padding:20px 28px; color:white;
      background:linear-gradient(115deg,#102a56,#155eef); box-shadow:0 3px 16px #102a5630 }
    header h1 { margin:0 0 4px; font-size:22px } header p { margin:0; opacity:.8 }
    main { max-width:1500px; margin:auto; padding:24px }
    .summary { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:12px; margin-bottom:18px }
    .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; padding:14px 16px }
    .card span { display:block; color:var(--muted); font-size:12px } .card strong { font-size:24px }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px }
    input,select,button { font:inherit } input,select { min-height:38px; border:1px solid var(--line);
      background:white; border-radius:8px; padding:8px 10px } input { min-width:260px; flex:1 }
    button { border:0; border-radius:8px; padding:9px 13px; font-weight:650; cursor:pointer }
    button:disabled { opacity:.42; cursor:not-allowed } .refresh,.select { color:var(--blue); background:#eaf1ff }
    .accept { color:white; background:var(--green) } .reject { color:var(--red); background:#feeceb }
    .table-wrap { overflow:auto; background:white; border:1px solid var(--line); border-radius:12px }
    table { width:100%; border-collapse:collapse; min-width:1150px } th { position:sticky; top:0;
      background:#edf2f8; color:#475569; text-align:left; font-size:12px; letter-spacing:.02em }
    th,td { padding:11px 12px; border-bottom:1px solid var(--line); vertical-align:top }
    tr:last-child td { border-bottom:0 } .money { font-variant-numeric:tabular-nums; font-weight:700 }
    .muted { color:var(--muted) } .ref { font-family:ui-monospace,SFMono-Regular,Menlo,monospace }
    .badge { display:inline-block; border-radius:999px; padding:3px 8px; font-size:12px; font-weight:700;
      background:#eef2f6; color:#475569 } .badge.pending { background:#fff4d6;color:#8a5700 }
    .badge.pushed { background:#dff7e9;color:#087443 } .badge.rejected { background:#feeceb;color:#b42318 }
    .badge.failed { background:#feeceb;color:#b42318 } .actions { display:flex; gap:7px; white-space:nowrap }
    .error { margin-top:5px; max-width:280px; color:var(--red); font-size:12px }
    .allocation { min-width:230px } .allocation div+div { margin-top:4px }
    .warning { color:#9a6700; font-size:12px; font-weight:650 }
    #notice { display:none; position:fixed; right:20px; bottom:20px; z-index:5; max-width:420px;
      color:white; background:#15233d; border-radius:10px; padding:12px 16px; box-shadow:0 8px 30px #0004 }
    @media(max-width:900px) { .summary{grid-template-columns:repeat(2,1fr)} main{padding:14px} }
  </style>
</head>
<body>
<header><h1>Payment Reconciliation</h1><p>Review Online and Cheque payment matches across HDFC, ICICI, and IDFC. Nothing is pushed until you accept it.</p></header>
<main>
  <section class="summary" id="summary"></section>
  <div class="toolbar">
    <input id="search" placeholder="Search customer, reference, amount, or narration">
    <select id="filter">
      <option value="all">All entries</option><option value="reviewable">Ready for review</option>
      <option value="unmatched">Unmatched</option><option value="pending">Pending</option>
      <option value="pushed">Pushed</option><option value="rejected">Rejected</option>
      <option value="failed">Failed</option>
    </select>
    <button class="select" id="selectReady">Select all ready</button>
    <button class="accept" id="acceptSelected" disabled>Accept selected &amp; Push</button>
    <span class="muted" id="selectedCount">0 selected</span>
    <button class="refresh" id="refresh">Refresh live data</button>
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th><input type="checkbox" id="selectVisible" title="Select all visible ready matches"></th><th>Status</th><th>Type</th><th>Payment / presented date</th><th>Customer</th><th>Bank</th><th>Amount</th>
      <th>Reference</th><th>Proposed bank line</th><th>Invoice allocation</th><th>Match result</th><th>Actions</th></tr></thead>
    <tbody id="rows"></tbody>
  </table></div>
</main><div id="notice"></div>
<script>
const token=document.querySelector('meta[name="review-token"]').content;
let batch={entries:[]},selected=new Set();
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>{const n=Number(String(v??'').replaceAll(',',''));return Number.isFinite(n)?n.toLocaleString('en-IN',{style:'currency',currency:'INR'}):esc(v)};
function state(e){return e.push_status==='pushed'?'pushed':e.push_status==='failed'?'failed':e.decision||'pending'}
function allocationHtml(e){const rows=e.invoice_allocations||[];if(!rows.length)return `<span class="muted">${esc(e.allocation_error||'No allocation recorded')}</span>`;const detail=rows.map(a=>`<div><strong>${esc(a.invoice_number||a.invoice_id)}</strong> · ${money(a.amount_applied)}<div class="muted">Due ${esc(a.due_date||'not set')} · balance ${money(a.balance)}</div></div>`).join('');const excess=Number(e.unallocated_amount||0)>0?`<div class="warning">${money(e.unallocated_amount)} will remain unused (invoice balances exhausted)</div>`:'';return detail+excess}
function notify(message,bad=false){const n=document.getElementById('notice');n.textContent=message;n.style.background=bad?'#b42318':'#15233d';n.style.display='block';setTimeout(()=>n.style.display='none',5000)}
function render(){
  const entries=batch.entries||[], counts={total:entries.length,reviewable:0,pending:0,pushed:0,rejected:0};
  entries.forEach(e=>{if(e.reviewable&&state(e)!=='pushed')counts.reviewable++;const s=state(e);if(s in counts)counts[s]++});
  document.getElementById('summary').innerHTML=[['Total',counts.total],['Ready',counts.reviewable],['Pending',counts.pending],['Pushed',counts.pushed],['Rejected',counts.rejected]].map(x=>`<div class="card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
  const q=document.getElementById('search').value.toLowerCase(), filter=document.getElementById('filter').value;
  const shown=entries.filter(e=>{const s=state(e), hay=JSON.stringify(e).toLowerCase();return (!q||hay.includes(q))&&(filter==='all'||(filter==='reviewable'&&e.reviewable&&s!=='pushed')||(filter==='unmatched'&&!e.reviewable)||s===filter)});
  const eligible=e=>e.reviewable&&state(e)!=='pushed'&&!['payment_created','match_requested','bank_matched','creator_updated'].includes(e.push_status);
  for(const id of [...selected]){const e=entries.find(x=>x.id===id);if(!e||!eligible(e))selected.delete(id)}
  document.getElementById('rows').innerHTML=shown.map(e=>{const c=e.creator||{},b=e.bank,s=state(e),busy=['payment_created','match_requested','bank_matched','creator_updated'].includes(e.push_status);return `<tr>
    <td><input type="checkbox" aria-label="Select payment" ${selected.has(e.id)?'checked':''} ${eligible(e)?'': 'disabled'} onchange="toggleEntry('${esc(e.id)}',this.checked)"></td><td><span class="badge ${esc(s)}">${esc(s)}</span>${e.push_status&&e.push_status!=='not_started'&&e.push_status!==s?`<div class="muted">${esc(e.push_status)}</div>`:''}${e.error?`<div class="error">${esc(e.error)}</div>`:''}</td><td><span class="badge">${esc(e.payment_type||'Online')}</span></td>
    <td>${esc(c.date)}<div class="muted">${esc(c.payment_id)}</div></td><td>${esc(c.customer_name)||'<span class="muted">Unknown</span>'}</td><td><strong>${esc(e.bank_name)||'<span class="muted">—</span>'}</strong></td>
    <td class="money">${money(c.amount)}</td><td class="ref">${esc(c.reference)||'<span class="muted">Missing</span>'}</td>
    <td>${b?`${esc(b.date)} · <span class="money">${money(b.amount)}</span><div class="ref">${esc(b.reference)}</div><div class="muted">${esc(b.description)}</div>`:'<span class="muted">No unique candidate</span>'}</td>
    <td class="allocation">${allocationHtml(e)}</td><td>${esc(e.reason)}</td><td><div class="actions"><button class="reject" onclick="rejectEntry('${esc(e.id)}')" ${s==='pushed'||busy||e.books_payment_id?'disabled':''}>Reject</button><button class="accept" onclick="acceptEntry('${esc(e.id)}')" ${!eligible(e)?'disabled':''}>Accept &amp; Push</button></div></td></tr>`}).join('');
  const visibleEligible=shown.filter(eligible);document.getElementById('selectVisible').checked=visibleEligible.length>0&&visibleEligible.every(e=>selected.has(e.id));
  document.getElementById('selectedCount').textContent=`${selected.size} selected`;document.getElementById('acceptSelected').disabled=selected.size===0;
}
async function api(path,method='GET',body={}){const r=await fetch(path,{method,headers:{'X-Review-Token':token,'Content-Type':'application/json'},body:method==='POST'?JSON.stringify({confirm:true,...body}):undefined});const data=await r.json();if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);return data}
async function load(){batch=await api('/api/batch');render()}
function toggleEntry(id,checked){if(checked)selected.add(id);else selected.delete(id);render()}
function visibleEligible(){const q=document.getElementById('search').value.toLowerCase(),filter=document.getElementById('filter').value;return (batch.entries||[]).filter(e=>{const s=state(e),hay=JSON.stringify(e).toLowerCase(),shown=(!q||hay.includes(q))&&(filter==='all'||(filter==='reviewable'&&e.reviewable&&s!=='pushed')||(filter==='unmatched'&&!e.reviewable)||s===filter);return shown&&e.reviewable&&s!=='pushed'&&!['payment_created','match_requested','bank_matched','creator_updated'].includes(e.push_status)})}
function toggleVisible(checked){for(const e of visibleEligible()){if(checked)selected.add(e.id);else selected.delete(e.id)}render()}
async function rejectEntry(id){if(!confirm('Reject this proposal? This only updates the local review queue.'))return;try{await api('/api/entries/'+encodeURIComponent(id)+'/reject','POST');await load();notify('Proposal rejected.')}catch(e){notify(e.message,true)}}
async function acceptEntry(id){if(!confirm('Accept and push this payment to Zoho Books now? Open invoices will be refreshed and allocated oldest-due-first before creation.'))return;try{notify('Refreshing invoices and pushing approved payment…');await api('/api/entries/'+encodeURIComponent(id)+'/accept','POST');await load();notify('Payment allocated, pushed, and matched successfully.')}catch(e){await load();notify(e.message,true)}}
async function acceptSelected(){const ids=[...selected];if(!ids.length)return;if(!confirm(`Accept and push ${ids.length} selected payment${ids.length===1?'':'s'} to Zoho Books? Each bank match and oldest-due-first invoice allocation is refreshed before posting.`))return;try{notify(`Allocating and pushing ${ids.length} selected payments sequentially…`);const result=await api('/api/accept-selected','POST',{entry_ids:ids});selected.clear();await load();const message=`${result.pushed.length} pushed${result.failed.length?`, ${result.failed.length} failed`:''}.`;notify(message,result.failed.length>0)}catch(e){await load();notify(e.message,true)}}
document.getElementById('search').addEventListener('input',render);document.getElementById('filter').addEventListener('change',render);
document.getElementById('selectVisible').onchange=e=>toggleVisible(e.target.checked);document.getElementById('selectReady').onclick=()=>{for(const e of batch.entries||[]){if(e.reviewable&&state(e)!=='pushed'&&!['payment_created','match_requested','bank_matched','creator_updated'].includes(e.push_status))selected.add(e.id)}render()};document.getElementById('acceptSelected').onclick=acceptSelected;
document.getElementById('refresh').onclick=async()=>{if(!confirm('Refresh proposals from live Creator and Books data? Existing decisions are preserved.'))return;try{notify('Refreshing…');batch=await api('/api/refresh','POST');render();notify('Review queue refreshed.')}catch(e){notify(e.message,true)}};
load().catch(e=>notify(e.message,true));
</script></body></html>"""


def _clients(token_url: str, owner: str, org_id: str, domain: str):
    provider = HttpTokenProvider(token_url, timeout=30)

    def token_for(primary: str, fallback: str) -> str:
        current = provider.get_tokens()
        return current.get(primary) or current.get(fallback) or ""

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
                    self._json(service.accept_many(entry_ids))
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
                    self._json(service.accept_and_push(entry_id))
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
    parser.add_argument("--creator-owner", default="bharathdst")
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
                ("Online", "Online_Payments"),
                ("Cheque", "Cheques"),
            ),
            state_path=args.state,
        ),
    )
    if not args.no_refresh or not args.state.exists():
        batch = service.refresh()
        logging.info("Loaded %s Creator payment review entries", len(batch["entries"]))
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
