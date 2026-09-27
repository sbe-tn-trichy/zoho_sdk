"""Repair unused credits on previously pushed payment-review Books payments."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from workflows.collection_reconciliation.allocator import (
    allocate_invoices_oldest_due_first,
    fetch_open_invoices,
)
from workflows.core.checkpoint import write_atomic_json
from workflows.core.matching import to_decimal, to_text


def _payment_payload(response: Mapping[str, Any]) -> Mapping[str, Any]:
    payment = response.get("payment", response)
    return payment if isinstance(payment, Mapping) else {}


def _update_payload(
    payment: Mapping[str, Any], allocations: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    totals: Dict[str, Decimal] = {}
    for row in list(payment.get("invoices") or []) + list(allocations):
        if not isinstance(row, Mapping):
            continue
        invoice_id = to_text(row.get("invoice_id"))
        amount = to_decimal(row.get("amount_applied"))
        if invoice_id and amount is not None:
            totals[invoice_id] = totals.get(invoice_id, Decimal("0")) + amount
    return {
        "invoices": [
            {"invoice_id": invoice_id, "amount_applied": float(amount)}
            for invoice_id, amount in totals.items()
        ]
    }


def _write_checkpoint(path: Path, payload: Mapping[str, Any]) -> None:
    write_atomic_json(path, payload, indent=2, default=str, max_retries=1)


def repair_payment_allocations(
    books: Any,
    state: Mapping[str, Any],
    *,
    execute: bool = False,
    checkpoint_path: Path = Path(
        "output/collection_reconciliation/payment_allocation_repair.json"
    ),
) -> Dict[str, Any]:
    """Audit and optionally allocate open invoices to payments with unused credits."""
    rows = []
    allocated_total = Decimal("0")
    for entry in state.get("entries") or []:
        if not isinstance(entry, Mapping) or entry.get("push_status") != "pushed":
            continue
        payment_id = to_text(entry.get("books_payment_id"))
        creator = entry.get("creator")
        creator = creator if isinstance(creator, Mapping) else {}
        customer_id = to_text(creator.get("books_customer_id"))
        row: Dict[str, Any] = {"entry_id": to_text(entry.get("id")), "payment_id": payment_id}
        if not payment_id or not customer_id:
            row["status"] = "incomplete_checkpoint"
            rows.append(row)
            continue
        payment = _payment_payload(books.customer_payments.get(payment_id))
        unused = to_decimal(payment.get("unused_amount")) or Decimal("0")
        if unused <= 0:
            row["status"] = "already_allocated"
            rows.append(row)
            continue
        invoices = fetch_open_invoices(books, customer_id)
        allocations, _remaining = allocate_invoices_oldest_due_first(unused, invoices)
        if not allocations:
            row["status"] = "no_open_invoices"
            rows.append(row)
            continue
        compact_allocations = [
            {
                "invoice_id": allocation["invoice_id"],
                "amount_applied": allocation["amount_applied"],
            }
            for allocation in allocations
        ]
        allocated = sum(
            (to_decimal(item["amount_applied"]) or Decimal("0") for item in compact_allocations),
            Decimal("0"),
        )
        allocated_total += allocated
        row["allocated_amount"] = float(allocated)
        row["allocations"] = compact_allocations
        if not execute:
            row["status"] = "planned"
        else:
            books.customer_payments.update(
                payment_id, _update_payload(payment, compact_allocations)
            )
            verified = _payment_payload(books.customer_payments.get(payment_id))
            verified_unused = to_decimal(verified.get("unused_amount"))
            if verified_unused is None or verified_unused >= unused:
                raise RuntimeError(
                    f"Books payment {payment_id} allocation was not verified."
                )
            row["status"] = "repaired"
        rows.append(row)
        _write_checkpoint(checkpoint_path, {"rows": rows})
    summary: Dict[str, Any] = {"scanned": len(rows), "allocated_amount": float(allocated_total)}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    result = {"summary": summary, "rows": rows}
    _write_checkpoint(checkpoint_path, result)
    return result
