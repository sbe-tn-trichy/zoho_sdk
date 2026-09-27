"""Propose location-based payment splits for FY 2025-26 manual-review rows."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.inter_location_split_proposals import propose_split


SOURCE = Path("output/inter_location_payment_proposals.json")
JSON_REPORT = Path("output/inter_location_split_proposals_fy2526.json")
MARKDOWN_REPORT = Path("output/inter_location_split_proposals_fy2526.md")
ALREADY_HANDLED = {"1094368000052871212"}


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if (source.get("view_id"), source.get("financial_year")) != (
        "264324000008274019", "FY 2025-26"
    ):
        raise ValueError("Unexpected source proposal")
    books = get_books_client()
    results = []
    for proposal in source["proposals"]:
        payment_id = str(proposal["payment_id"])
        if payment_id in ALREADY_HANDLED:
            continue
        kind = proposal["payment_type"]
        if kind == "Customer Payment":
            payment = books.customer_payments.get(payment_id)["payment"]
            allocations = payment.get("invoices") or []
            documents = [books.invoices.get(str(a["invoice_id"]))["invoice"] for a in allocations]
        elif kind == "Vendor Payment":
            payment = books.vendor_payments.get(payment_id)["vendorpayment"]
            allocations = payment.get("bills") or []
            documents = [books.bills.get(str(a["bill_id"]))["bill"] for a in allocations]
        else:
            raise ValueError(f"Unsupported payment type: {kind}")
        results.append(propose_split(proposal, payment, documents))
    counts = Counter(result["status"] for result in results)
    report = {"source_view_id": source["view_id"], "financial_year": source["financial_year"],
              "excluded_handled_payment_ids": sorted(ALREADY_HANDLED),
              "checked_count": len(results), "status_counts": dict(counts), "proposals": results}
    JSON_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# FY 2025–26 location split proposals", "",
             f"Checked {len(results)} current Books payments; {counts['split_proposed']} splits proposed; "
             f"{counts['manual_review']} other manual reviews.", "",
             "These are proposals only. No Books payments were changed.", "",
             "| Type | Payment | Current number | Date | Existing amount | Keep at current location | Create in other location(s) | Reason |",
             "| --- | --- | --- | --- | ---: | --- | --- | --- |"]
    for item in results:
        retain = item["retain"]
        keep = (f"{retain['location']}: {retain['amount']} " +
                ", ".join(d["number"] for d in retain["documents"])) if retain else ""
        create = "; ".join(
            f"{part['location']}: {part['amount']} " +
            ", ".join(d["number"] for d in part["documents"])
            for part in item["create"])
        values = (item["payment_type"], item["payment_id"], item["payment_number"],
                  item["date"], item["amount"], keep, create, item["reason"])
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |")
    lines.append("")
    MARKDOWN_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Checked {len(results)}: {counts['split_proposed']} split proposals, "
          f"{counts['manual_review']} other manual reviews. Reports: {MARKDOWN_REPORT}, {JSON_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
