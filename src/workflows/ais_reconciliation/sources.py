"""Bounded read-only Books collection and explicit, replayable snapshots."""
from __future__ import annotations

import json
import math
import time
from calendar import month_name
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

from .master import Master
from workflows.gstr3b_pnl_comparison import ComparisonConfig, compare_gstr3b_to_pnl

from workflows.core.checkpoint import write_atomic_json


class SnapshotMetadata(TypedDict):
    version: int
    organization_id: str
    from_date: str
    to_date: str
    captured_at: str
    complete: bool
    requests: int


class BooksSnapshot(TypedDict):
    metadata: SnapshotMetadata
    data: dict[str, Any]


@dataclass(frozen=True)
class CollectionConfig:
    organization_id: str
    gstin: str
    sales_account_id: str
    excluded_location_id: str
    request_interval: float = 2.1
    max_requests: int = 250

    def __post_init__(self) -> None:
        if not all((self.organization_id, self.gstin, self.sales_account_id, self.excluded_location_id)):
            raise ValueError("Organization, GSTIN, Sales account and excluded location are required")
        if not math.isfinite(self.request_interval) or self.request_interval < 1.0 or self.max_requests < 1:
            raise ValueError("Use at least one second between requests and a positive request budget")


def master_range(master: Master) -> tuple[str, str]:
    years = sorted(2000 + int(n[:2]) for n in master if n.endswith(" GST purchases"))
    return f"{years[0]}-04-01", f"{years[-1]+1}-03-31"


def read_snapshot(path: Path | str, *, organization_id: str,
                  from_date: str, to_date: str) -> BooksSnapshot:
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = snapshot.get("metadata", {})
    if (meta.get("version") != 1 or meta.get("complete") is not True
            or meta.get("organization_id") != organization_id
            or meta.get("from_date") != from_date or meta.get("to_date") != to_date
            or not meta.get("captured_at")):
        raise ValueError("Snapshot is incomplete or belongs to another organization/date range")
    for key in ("organization", "locations", "contacts", "accounts", "bills", "vendor_credits",
                "expenses", "input_tax_ledger", "tax_income_ledger", "bank_windows"):
        if key not in snapshot.get("data", {}):
            raise ValueError(f"Snapshot lacks {key}")
    if str(snapshot["data"]["organization"]["organization"]["organization_id"]) != organization_id:
        raise ValueError("Organization response disagrees with snapshot identity")
    for year in range(int(from_date[:4]), int(to_date[:4])):
        if f"sales_{str(year)[2:]}-{str(year+1)[2:]}" not in snapshot["data"]:
            raise ValueError("Snapshot lacks a complete FY sales comparison")
    return snapshot


def write_snapshot(snapshot: BooksSnapshot, path: Path | str) -> Path:
    target = Path(path)
    write_atomic_json(target, snapshot, indent=None, ensure_ascii=True, default=str)
    return target


def collect_books_snapshot(books: Any, master: Master, config: CollectionConfig) -> BooksSnapshot:
    """Collect lists and only input-tax/receivable ledgers; stop at a request budget.

    No per-invoice API fanout, customer-payment download, inventory reads, or
    income/bank ledger scans. Bank reads use merged +/-7 day AIS windows.
    Throttling errors propagate rather than repeatedly extending a security block.
    """
    if str(books.organization_id) != config.organization_id:
        raise ValueError("Books client organization differs from collection configuration")
    start, end = master_range(master)
    captured = datetime.now().astimezone().isoformat(timespec="seconds")
    calls = 0
    last = float("-inf")

    def paced(fn):
        nonlocal calls, last
        if calls >= config.max_requests:
            raise RuntimeError("AIS Books request budget exhausted; no complete report produced")
        time.sleep(max(0, config.request_interval - (time.monotonic() - last)))
        last = time.monotonic()
        calls += 1
        response = fn()
        if isinstance(response, dict) and response.get("code", 0) != 0:
            raise ValueError(f"Books read failed: code {response.get('code')}")
        return response

    def listing(resource, key, params=None):
        rows = []
        page = 1
        seen = set()
        while True:
            response = paced(lambda: resource.list({**(params or {}), "page": page, "per_page": 200}))
            if key not in response or not isinstance(response[key], list):
                raise ValueError(f"Books response missing list {key}")
            part = response[key]
            signature = json.dumps(part, sort_keys=True)
            if part and signature in seen:
                raise ValueError("Books repeated a page; refusing incomplete reconciliation")
            seen.add(signature)
            rows.extend(part)
            context = response.get("page_context", {})
            if not isinstance(context.get("has_more_page"), bool):
                raise ValueError("Books response lacks pagination completeness")
            if not context["has_more_page"]:
                return rows
            if not part:
                raise ValueError("Empty Books page claims more records")
            page += 1

    def ledger(ids, first, final):
        if not ids:
            return []
        rows = []
        page = 1
        def walk(nodes):
            for node in nodes:
                if "account_transactions" in node:
                    yield from walk(node["account_transactions"])
                elif "transaction_id" in node:
                    yield node
        seen = set()
        while True:
            response = paced(lambda: books.registers.list_transactions_for_accounts(
                ids, from_date=first, to_date=final, page=page, per_page=200))
            ctx = response.get("page_context", {})
            if ctx.get("from_date") != first or ctx.get("to_date") != final:
                raise ValueError("Books ignored ledger date scope")
            part = list(walk(response["register_transactions"]["account_transactions"]))
            signature = json.dumps(part, sort_keys=True)
            if part and signature in seen:
                raise ValueError("Books repeated a ledger page")
            seen.add(signature)
            if any(str(row["account_id"]) not in ids or not first <= row["date"] <= final for row in part):
                raise ValueError("Books ignored ledger account/date filter")
            rows.extend(part)
            if not isinstance(ctx.get("has_more_page"), bool):
                raise ValueError("Missing ledger pagination completeness")
            if not ctx["has_more_page"]:
                return rows
            if not part:
                raise ValueError("Empty ledger page claims more records")
            page += 1

    data = {"organization": paced(lambda: books.organizations.get(config.organization_id))}
    for name, key in (("locations", "locations"), ("chart_of_accounts", "chartofaccounts"), ("contacts", "contacts")):
        data["accounts" if name == "chart_of_accounts" else name] = listing(getattr(books, name), key)
    if not any(r.get("tax_reg_no") == config.gstin for r in data["locations"]):
        raise ValueError("AIS GSTIN has no Books location")
    other_registrations = {r["location_id"] for r in data["locations"]
                           if r.get("tax_reg_no") and r["tax_reg_no"] != config.gstin}
    if other_registrations != {config.excluded_location_id}:
        raise ValueError("Sales scope requires exactly the configured other-GSTIN location; override or review scope")
    dates = {"date_start": start, "date_end": end}
    for name, key in (("bills", "bills"), ("vendor_credits", "vendor_credits"), ("expenses", "expenses")):
        data[name] = listing(getattr(books, name), key, dates)
        if any(not start <= d["date"] <= end for d in data[name]):
            raise ValueError(f"Books ignored date filter for {name}")
    accounts = data["accounts"]
    for name, wanted in (("input_tax_ledger", {"Input IGST", "Input CGST", "Input SGST", "Input CESS", "TCS Receivable"}),
                         ("tax_income_ledger", {"TDS Receivable", "TCS Receivable", "Advance Tax"})):
        ids = [str(a["account_id"]) for a in accounts if a["account_name"] in wanted]
        if name == "tax_income_ledger" and not {"TDS Receivable", "TCS Receivable"} <= {a["account_name"] for a in accounts}:
            raise ValueError("Required TDS/TCS receivable accounts not found")
        data[name] = ledger(ids, start, end)
    windows = []
    for tab, col in (("Tax payments", "I"), ("Refunds", "G")):
        for row in master[tab][1:]:
            day = datetime.strptime(row["cells"][col], "%d/%m/%Y")
            windows.append((day - timedelta(days=7), day + timedelta(days=7)))
    merged = []
    for first, final in sorted(windows):
        if merged and first <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(final, merged[-1][1]))
        else:
            merged.append((first, final))
    bank_ids = [str(a["account_id"]) for a in accounts if a["account_type"] == "bank"]
    data["bank_windows"] = [r for first, final in merged for r in ledger(bank_ids, first.strftime("%Y-%m-%d"), final.strftime("%Y-%m-%d"))]
    # Reuse existing audited P&L scope/context and month-to-FY validation.
    adapter = SimpleNamespace(chart_of_accounts=SimpleNamespace(list_all=lambda: accounts),
                              request=lambda *a, **kw: paced(lambda: books.request(*a, **kw)))
    for prefix in sorted(n.removesuffix(" GST sales") for n in master if n.endswith(" GST sales")):
        returns = []
        for row in master[prefix + " GST sales"][1:]:
            c = row["cells"]
            if c["I"] == "Active":
                day = datetime.strptime(c["F"], "%b-%Y")
                returns.append({"period": month_name[day.month], "filing_status": "FILED",
                                "table_3_1_supplies": {"outward_taxable_supplies": {"taxable_value": c["H"]}}})
        data["sales_" + prefix] = compare_gstr3b_to_pnl(adapter, {"filing_year": "20" + prefix, "returns": returns},
            ComparisonConfig(config.sales_account_id, config.excluded_location_id))
    return {"metadata": {"version": 1, "organization_id": config.organization_id, "from_date": start,
            "to_date": end, "captured_at": captured, "complete": True, "requests": calls}, "data": data}
