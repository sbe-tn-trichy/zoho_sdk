"""Human-readable reporting for duplicate customer-payment checks."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping


def _text(value: Any) -> str:
    return escape("" if value is None else str(value))


def _markdown_text(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("`", "\\`").replace("\n", " ").strip()


def _display_amount(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value or "")


def render_markdown_report(payload: Mapping[str, Any]) -> str:
    """Render duplicate payments as customer/date headings and payment bullets."""
    result = payload["result"]
    lines = [
        "# Duplicate Customer Payments",
        "",
        f"Payments scanned: {int(result['payments_scanned']):,}  ",
        f"Potential duplicate groups: {int(result['duplicate_group_count']):,}  ",
        f"Payments in flagged groups: {int(result['duplicate_payment_count']):,}",
        "",
    ]
    for group in result["duplicate_groups"]:
        customer = _markdown_text(group.get("customer_name")) or _markdown_text(group.get("customer_id"))
        lines.extend([f"## {customer}, {_markdown_text(group.get('date'))}", ""])
        for payment in group["payments"]:
            reference = _markdown_text(payment.get("reference_number")) or "No reference"
            amount = _display_amount(payment.get("amount", group.get("amount")))
            lines.append(f"- {reference}, {amount}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html_report(payload: Mapping[str, Any]) -> str:
    """Render a standalone, searchable HTML report from a check payload."""
    result = payload["result"]
    rows = []
    for group_number, group in enumerate(result["duplicate_groups"], start=1):
        for payment in group["payments"]:
            search = " ".join(
                str(value or "")
                for value in (
                    group.get("customer_name"), group.get("customer_id"), group.get("date"),
                    group.get("amount"), payment.get("payment_number"),
                    payment.get("reference_number"), payment.get("payment_mode"),
                )
            ).lower()
            rows.append(
                f'<tr data-search="{_text(search)}">'
                f'<td>{group_number}</td><td>{_text(group["date"])}</td>'
                f'<td><strong>{_text(group.get("customer_name"))}</strong><small>{_text(group["customer_id"])}</small></td>'
                f'<td class="amount">{_text(group["amount"])}</td><td>{group["payment_count"]}</td>'
                f'<td>{_text(payment.get("payment_number"))}</td>'
                f'<td>{_text(payment.get("reference_number"))}</td>'
                f'<td>{_text(payment.get("payment_mode"))}</td>'
                f'<td class="id">{_text(payment.get("payment_id"))}</td></tr>'
            )

    duplicate_groups = int(result["duplicate_group_count"])
    duplicate_payments = int(result["duplicate_payment_count"])
    excess = duplicate_payments - duplicate_groups
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duplicate Customer Payments</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#dbe3ec;--navy:#16324f;--blue:#e8f1fa;--amber:#fff4d6;--red:#b42318;--bg:#f5f7fa}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1440px;margin:auto;padding:32px}} h1{{margin:0 0 4px;font-size:28px}} .subtitle{{color:var(--muted);margin-bottom:24px}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:14px;margin-bottom:22px}} .card{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px}}
.card span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}} .card strong{{display:block;font-size:26px;margin-top:4px}} .warn strong{{color:var(--red)}}
.note{{background:var(--amber);border-left:4px solid #d69e2e;padding:12px 14px;margin:0 0 18px;border-radius:4px}}
.toolbar{{display:flex;gap:12px;align-items:center;margin-bottom:10px}} input{{width:min(520px,100%);padding:10px 12px;border:1px solid #b7c3d0;border-radius:7px;font:inherit}} #visible{{color:var(--muted)}}
.table-wrap{{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:10px}} table{{width:100%;border-collapse:collapse;white-space:nowrap}} th{{position:sticky;top:0;background:var(--navy);color:#fff;text-align:left;padding:11px 10px;font-size:12px;letter-spacing:.03em}} td{{padding:10px;border-bottom:1px solid #edf1f5;vertical-align:top}} tbody tr:nth-child(even){{background:#f8fafc}} tbody tr:hover{{background:var(--blue)}}
td small{{display:block;color:var(--muted);font-size:11px}} .amount{{text-align:right;font-variant-numeric:tabular-nums}} .id{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}} footer{{color:var(--muted);margin-top:14px;font-size:12px}}
@media(max-width:760px){{main{{padding:18px}}.cards{{grid-template-columns:repeat(2,1fr)}}}}
@media print{{body{{background:#fff}}main{{max-width:none;padding:0}}.toolbar{{display:none}}.table-wrap{{overflow:visible;border:0}}th{{position:static}}}}
</style></head><body><main>
<h1>Duplicate Customer Payments</h1>
<div class="subtitle">Zoho Books · checked {_text(payload.get("checked_at"))}</div>
<section class="cards">
<div class="card"><span>Payments scanned</span><strong>{int(result["payments_scanned"]):,}</strong></div>
<div class="card warn"><span>Potential duplicate groups</span><strong>{duplicate_groups:,}</strong></div>
<div class="card"><span>Payments in flagged groups</span><strong>{duplicate_payments:,}</strong></div>
<div class="card"><span>Excess entries</span><strong>{excess:,}</strong></div>
</section>
<p class="note"><strong>Review required:</strong> matching customer, date, and amount indicates a potential duplicate. Different references can represent legitimate separate payments.</p>
<div class="toolbar"><input id="search" type="search" placeholder="Search customer, date, amount, payment number, reference or mode…"><span id="visible">{len(rows)} rows</span></div>
<div class="table-wrap"><table><thead><tr><th>Group</th><th>Date</th><th>Customer</th><th>Amount</th><th>Group size</th><th>Payment no.</th><th>Reference</th><th>Mode</th><th>Payment ID</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<footer>Organization ID: {_text(payload.get("organization_id"))} · Skipped records: {len(result.get("skipped", []))}</footer>
</main><script>
const input=document.getElementById('search'),rows=[...document.querySelectorAll('tbody tr')],visible=document.getElementById('visible');
input.addEventListener('input',()=>{{const q=input.value.trim().toLowerCase();let n=0;rows.forEach(r=>{{const show=!q||r.dataset.search.includes(q);r.hidden=!show;if(show)n++}});visible.textContent=n+' rows'}});
</script></body></html>"""
