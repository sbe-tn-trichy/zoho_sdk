"""Apply reviewed invoice payment date updates to Zoho Books."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from zoho.helpers import unwrap_record

logger = logging.getLogger(__name__)


@dataclass
class PaymentUpdateResult:
    payment_id: str
    payment_number: str
    status: str  # "updated", "skipped", "failed", "planned"
    total_allocations: int
    updated_allocations: int
    error: Optional[str] = None


class CustomerPaymentDateUpdater:
    """Updates customer payment invoice application dates in Zoho Books."""

    def __init__(self, books_client: Any):
        self.books = books_client

    def prepare_payment_payload(
        self,
        payment_detail: Mapping[str, Any],
        target_allocations_by_inv: Mapping[str, str],  # invoice_id -> target_date (YYYY-MM-DD)
    ) -> Dict[str, Any]:
        """Construct the update payload for a customer payment preserving existing amounts and other fields."""
        invoices_payload = []
        for inv in payment_detail.get("invoices") or []:
            inv_id = str(inv.get("invoice_id") or "").strip()
            amt = float(inv.get("amount_applied") or inv.get("amount") or 0.0)
            if not inv_id or amt <= 0:
                continue

            inv_entry: Dict[str, Any] = {
                "invoice_id": inv_id,
                "amount_applied": amt,
            }
            if inv.get("invoice_payment_id"):
                inv_entry["invoice_payment_id"] = inv["invoice_payment_id"]
            if inv.get("tax_amount_withheld") is not None:
                inv_entry["tax_amount_withheld"] = float(inv.get("tax_amount_withheld") or 0.0)

            if inv_id in target_allocations_by_inv:
                target_dt = target_allocations_by_inv[inv_id]
                inv_entry["date"] = target_dt
                inv_entry["apply_date"] = target_dt
            elif inv.get("apply_date"):
                inv_entry["date"] = inv.get("apply_date")
                inv_entry["apply_date"] = inv.get("apply_date")
            elif inv.get("date"):
                inv_entry["date"] = inv.get("date")
                inv_entry["apply_date"] = inv.get("date")

            invoices_payload.append(inv_entry)

        payload: Dict[str, Any] = {"invoices": invoices_payload}
        for field in ("customer_id", "payment_mode", "date", "account_id", "reference_number", "description", "exchange_rate", "bank_charges"):
            val = payment_detail.get(field)
            if val is not None:
                payload[field] = val
        if payment_detail.get("amount") is not None:
            payload["amount"] = float(payment_detail["amount"])

        return payload

    def execute_plan(
        self,
        plan: Mapping[str, Any],
        *,
        execute: bool = False,
        checkpoint_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Execute the date update plan across all affected customer payments."""
        by_payment = plan.get("by_payment") or {}
        results: List[Dict[str, Any]] = []
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for pmt_num, allocations in by_payment.items():
            if not allocations:
                continue

            pmt_id = allocations[0]["payment_id"]
            cust_name = allocations[0]["customer_name"]

            # Map invoice_id -> target_applied_date
            targets_by_inv = {
                item["invoice_id"]: item["target_applied_date"]
                for item in allocations
                if item.get("invoice_id") and item.get("target_applied_date")
            }

            if not execute:
                results.append({
                    "payment_id": pmt_id,
                    "payment_number": pmt_num,
                    "customer_name": cust_name,
                    "status": "planned",
                    "allocations_count": len(allocations),
                    "target_dates": targets_by_inv,
                })
                continue

            try:
                # Fetch fresh payment from Books
                raw = self.books.customer_payments.get(pmt_id)
                current_pmt = unwrap_record(raw, ("payment", "customerpayment"))
                
                payload = self.prepare_payment_payload(current_pmt, targets_by_inv)
                self.books.customer_payments.update(pmt_id, payload)

                results.append({
                    "payment_id": pmt_id,
                    "payment_number": pmt_num,
                    "customer_name": cust_name,
                    "status": "updated",
                    "allocations_count": len(allocations),
                    "target_dates": targets_by_inv,
                })
                success_count += 1
            except Exception as exc:
                logger.exception("Failed to update payment %s (%s)", pmt_num, pmt_id)
                results.append({
                    "payment_id": pmt_id,
                    "payment_number": pmt_num,
                    "customer_name": cust_name,
                    "status": "failed",
                    "allocations_count": len(allocations),
                    "error": str(exc),
                })
                failed_count += 1

        summary = {
            "total_payments": len(by_payment),
            "planned": len(results) if not execute else 0,
            "updated": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "dry_run": not execute,
        }

        output_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "results": results,
        }

        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(json.dumps(output_payload, indent=2) + "\n", encoding="utf-8")

        return output_payload
