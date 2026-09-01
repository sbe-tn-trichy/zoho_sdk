"""Settle linked customer and vendor balances through a clearing bank account."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from zoho.helpers import (
    GSTIN_PATTERN,
    find_bank_account_by_name,
    is_valid_gstin,
    normalize_gstin,
)
from ..core.matching import to_decimal


class VendorCustomerOffsetError(RuntimeError):
    """Raised when a safe two-sided offset cannot be completed."""


@dataclass(frozen=True)
class VendorCustomerOffsetConfig:
    """Policy and posting settings for customer/vendor balance offsets."""

    bank_account_name: str = "Vendor To Customer"
    bank_account_id: Optional[str] = None
    payment_mode: str = "banktransfer"
    reference_prefix: str = "Vendor-Customer Offset"
    dry_run: bool = True
    ensure_linked: bool = True
    vendor_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.bank_account_id and not self.bank_account_name.strip():
            raise ValueError("bank_account_id or bank_account_name is required.")
        if not self.payment_mode.strip():
            raise ValueError("payment_mode is required.")


def _decimal(value: Any) -> Decimal:
    return to_decimal(value) or Decimal("0")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _contact_type(contact: Mapping[str, Any]) -> str:
    return str(contact.get("contact_type") or "").strip().lower()


def _unique_gstin_pairs(
    contacts: Iterable[Mapping[str, Any]],
) -> Tuple[
    List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]],
    List[Dict[str, Any]],
]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for contact in contacts:
        gstin = normalize_gstin(contact.get("gst_no"))
        if gstin:
            grouped[gstin].append(contact)

    pairs: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    skipped: List[Dict[str, Any]] = []
    for gstin, matches in grouped.items():
        customers = [item for item in matches if _contact_type(item) == "customer"]
        vendors = [item for item in matches if _contact_type(item) == "vendor"]
        if not customers or not vendors:
            continue
        if (
            not is_valid_gstin(gstin)
            or len(matches) != 2
            or len(customers) != 1
            or len(vendors) != 1
        ):
            skipped.append(
                {
                    "gstin": gstin,
                    "reason": "ambiguous_gstin",
                    "customer_count": len(customers),
                    "vendor_count": len(vendors),
                }
            )
            continue
        pairs.append((gstin, customers[0], vendors[0]))
    return pairs, skipped


def _resolve_bank_account_id(books_client: Any, config: VendorCustomerOffsetConfig) -> str:
    if config.bank_account_id:
        return config.bank_account_id

    account = find_bank_account_by_name(books_client, config.bank_account_name)
    if not account:
        raise VendorCustomerOffsetError(
            f"Expected exactly one bank account named {config.bank_account_name!r}; found 0."
        )
    account_id = str(account.get("account_id") or "")
    if not account_id:
        raise VendorCustomerOffsetError("The clearing bank account has no account_id.")
    return account_id


def _document_sort_key(document: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(document.get("due_date") or "9999-12-31"),
        str(document.get("date") or "9999-12-31"),
        str(document.get("invoice_id") or document.get("bill_id") or ""),
    )


def _allocate_documents(
    documents: Sequence[Mapping[str, Any]],
    amount: Decimal,
    id_key: str,
) -> Tuple[List[Dict[str, Any]], Decimal]:
    remaining = amount
    allocations: List[Dict[str, Any]] = []
    for document in sorted(documents, key=_document_sort_key):
        if remaining <= 0:
            break
        balance = _money(_decimal(document.get("balance")))
        document_id = str(document.get(id_key) or "")
        if not document_id or balance <= 0:
            continue
        applied = min(balance, remaining)
        allocations.append({id_key: document_id, "amount_applied": float(applied)})
        remaining = _money(remaining - applied)
    return allocations, remaining


def _build_bill_payment_tranches(
    invoices: Sequence[Mapping[str, Any]],
    bills: Sequence[Mapping[str, Any]],
    amount: Decimal,
) -> Tuple[List[Dict[str, Any]], Decimal, str]:
    """Split an offset into one same-dated payment pair per vendor bill."""
    invoice_allocations, invoice_remaining = _allocate_documents(
        invoices, amount, "invoice_id"
    )
    bill_allocations, bill_remaining = _allocate_documents(bills, amount, "bill_id")
    if invoice_remaining or bill_remaining:
        return [], max(invoice_remaining, bill_remaining), "insufficient_open_documents"

    bill_by_id = {str(item.get("bill_id") or ""): item for item in bills}
    invoice_index = 0
    invoice_available = (
        _money(_decimal(invoice_allocations[0]["amount_applied"]))
        if invoice_allocations
        else Decimal("0")
    )
    tranches: List[Dict[str, Any]] = []
    for bill_allocation in bill_allocations:
        bill_id = str(bill_allocation["bill_id"])
        bill = bill_by_id[bill_id]
        try:
            payment_date = date.fromisoformat(str(bill.get("date") or ""))
        except ValueError:
            return [], amount, "missing_vendor_invoice_date"

        tranche_amount = _money(_decimal(bill_allocation["amount_applied"]))
        tranche_remaining = tranche_amount
        tranche_invoices: List[Dict[str, Any]] = []
        while tranche_remaining > 0 and invoice_index < len(invoice_allocations):
            applied = min(invoice_available, tranche_remaining)
            tranche_invoices.append(
                {
                    "invoice_id": invoice_allocations[invoice_index]["invoice_id"],
                    "amount_applied": float(applied),
                }
            )
            tranche_remaining = _money(tranche_remaining - applied)
            invoice_available = _money(invoice_available - applied)
            if invoice_available == 0:
                invoice_index += 1
                if invoice_index < len(invoice_allocations):
                    invoice_available = _money(
                        _decimal(invoice_allocations[invoice_index]["amount_applied"])
                    )

        if tranche_remaining:
            return [], tranche_remaining, "insufficient_open_documents"
        tranches.append(
            {
                "amount": tranche_amount,
                "payment_date": payment_date,
                "invoice_allocations": tranche_invoices,
                "bill_allocations": [bill_allocation],
            }
        )
    return tranches, Decimal("0"), ""


def _open_documents(books_client: Any, customer_id: str, vendor_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    invoices = books_client.invoices.list_all(params={"customer_id": customer_id})
    bills = books_client.bills.list_all(params={"vendor_id": vendor_id})
    excluded_statuses = {
        "void",
        "draft",
        "paid",
        "rejected",
        "pending_approval",
        "approval_overdue",
    }

    def is_open(document: Mapping[str, Any]) -> bool:
        status = str(document.get("status") or "").strip().lower()
        return _decimal(document.get("balance")) > 0 and status not in excluded_statuses

    return (
        [item for item in invoices if is_open(item)],
        [item for item in bills if is_open(item)],
    )


def _ensure_linked(books_client: Any, customer_id: str, vendor_id: str) -> str:
    """Ensure the pair is linked using the Books web-client endpoint.

    Zoho's public OpenAPI does not publish this operation. The live Books client
    uses POST /customers/{customer_id}/link with form-encoded vendor_id. Code
    3051 is the idempotent "already linked" response.
    """
    try:
        response = books_client.request(
            "POST",
            f"customers/{customer_id}/link",
            data={"vendor_id": vendor_id},
        )
    except Exception as exc:
        message = str(exc)
        if '"code":3051' in message or "already linked" in message.lower():
            return "already_linked"
        raise VendorCustomerOffsetError(
            f"Could not verify the customer/vendor link: {message}"
        ) from exc
    if response.get("code") == 0:
        return "linked"
    raise VendorCustomerOffsetError(
        f"Could not link customer/vendor pair: {response.get('message', 'unknown error')}"
    )


def _payment_id(response: Mapping[str, Any], container: str) -> str:
    payment = response.get(container) or response.get("payment") or {}
    return str(payment.get("payment_id") or payment.get("vendorpayment_id") or "")


def _reference_number(prefix: str, bill_id: str) -> str:
    """Build a bill-specific reference within Books' live 50-character limit."""
    return f"{prefix.strip()} {bill_id}"[:50]


def run_vendor_customer_offset(
    books_client: Any,
    config: Optional[VendorCustomerOffsetConfig] = None,
) -> Dict[str, Any]:
    """Create paired, fully-applied payments for linked customer/vendor contacts.

    Contacts are paired only when a valid GSTIN occurs exactly once as a customer
    and exactly once as a vendor. Payments are applied oldest-due-first. A pair
    is skipped if either balance is non-positive, currencies differ, or open
    documents cannot absorb the calculated offset completely.
    """
    config = config or VendorCustomerOffsetConfig()
    bank_account_id = _resolve_bank_account_id(books_client, config)
    contacts = books_client.contacts.list_all(params={"filter_by": "Status.Active"})
    pairs, skipped = _unique_gstin_pairs(contacts)
    if config.vendor_id:
        pairs = [
            pair
            for pair in pairs
            if str(pair[2].get("contact_id") or "") == config.vendor_id
        ]
    results: Dict[str, Any] = {
        "dry_run": config.dry_run,
        "bank_account_id": bank_account_id,
        "candidate_pairs": len(pairs),
        "planned": [],
        "posted": [],
        "skipped": skipped,
        "failed": [],
    }

    for gstin, customer, vendor in pairs:
        customer_id = str(customer.get("contact_id") or "")
        vendor_id = str(vendor.get("contact_id") or "")
        customer_currency = str(customer.get("currency_code") or "")
        vendor_currency = str(vendor.get("currency_code") or "")
        receivable = _money(_decimal(customer.get("outstanding_receivable_amount")))
        payable = _money(_decimal(vendor.get("outstanding_payable_amount")))
        amount = min(receivable, payable)
        pair_summary = {
            "gstin": gstin,
            "customer_id": customer_id,
            "vendor_id": vendor_id,
            "amount": float(amount),
        }

        if not customer_id or not vendor_id:
            results["skipped"].append({**pair_summary, "reason": "missing_contact_id"})
            continue
        if customer_currency != vendor_currency:
            results["skipped"].append({**pair_summary, "reason": "currency_mismatch"})
            continue
        if amount <= 0:
            results["skipped"].append({**pair_summary, "reason": "no_mutual_outstanding"})
            continue

        invoices, bills = _open_documents(books_client, customer_id, vendor_id)
        tranches, unallocated, tranche_error = _build_bill_payment_tranches(
            invoices, bills, amount
        )
        if tranche_error:
            results["skipped"].append(
                {
                    **pair_summary,
                    "reason": tranche_error,
                    "unallocated_amount": float(unallocated),
                }
            )
            continue

        if config.dry_run:
            for tranche in tranches:
                results["planned"].append(
                    {
                        **pair_summary,
                        "amount": float(tranche["amount"]),
                        "payment_date": tranche["payment_date"].isoformat(),
                        "invoice_allocations": tranche["invoice_allocations"],
                        "bill_allocations": tranche["bill_allocations"],
                        "link_status": "not_checked_in_dry_run",
                    }
                )
            continue

        try:
            link_status = (
                _ensure_linked(books_client, customer_id, vendor_id)
                if config.ensure_linked
                else "assumed_linked"
            )
        except Exception as exc:
            results["failed"].append(
                {**pair_summary, "error": str(exc), "rollback": "not_required"}
            )
            continue

        for tranche in tranches:
            payment_date_text = tranche["payment_date"].isoformat()
            tranche_amount = tranche["amount"]
            bill_id = tranche["bill_allocations"][0]["bill_id"]
            reference = _reference_number(config.reference_prefix, bill_id)
            customer_payload = {
                "customer_id": customer_id,
                "payment_mode": config.payment_mode,
                "amount": float(tranche_amount),
                "date": payment_date_text,
                "account_id": bank_account_id,
                "reference_number": reference,
                "description": "Offset against linked vendor payable",
                "invoices": tranche["invoice_allocations"],
            }
            vendor_payload = {
                "vendor_id": vendor_id,
                "payment_mode": config.payment_mode,
                "amount": float(tranche_amount),
                "date": payment_date_text,
                "paid_through_account_id": bank_account_id,
                "reference_number": reference,
                "description": "Offset against linked customer receivable",
                "bills": tranche["bill_allocations"],
            }
            customer_payment_id = ""
            try:
                customer_response = books_client.customer_payments.create(customer_payload)
                customer_payment_id = _payment_id(customer_response, "payment")
                if not customer_payment_id:
                    raise VendorCustomerOffsetError(
                        "Zoho did not return the created customer payment ID."
                    )
                vendor_response = books_client.vendor_payments.create(vendor_payload)
                vendor_payment_id = _payment_id(vendor_response, "vendorpayment")
                if not vendor_payment_id:
                    raise VendorCustomerOffsetError(
                        "Zoho did not return the created vendor payment ID."
                    )
                results["posted"].append(
                    {
                        **pair_summary,
                        "amount": float(tranche_amount),
                        "bill_id": bill_id,
                        "payment_date": payment_date_text,
                        "customer_payment_id": customer_payment_id,
                        "vendor_payment_id": vendor_payment_id,
                        "link_status": link_status,
                    }
                )
            except Exception as exc:
                rollback = "not_required"
                if customer_payment_id:
                    try:
                        books_client.customer_payments.delete(customer_payment_id)
                        rollback = "customer_payment_deleted"
                    except Exception as rollback_exc:
                        rollback = f"failed: {rollback_exc}"
                results["failed"].append(
                    {
                        **pair_summary,
                        "amount": float(tranche_amount),
                        "bill_id": bill_id,
                        "payment_date": payment_date_text,
                        "error": str(exc),
                        "rollback": rollback,
                    }
                )
                break

    results["summary"] = {
        "planned": len(results["planned"]),
        "posted": len(results["posted"]),
        "planned_customer_payments": len(results["planned"]),
        "planned_vendor_payments": len(results["planned"]),
        "posted_customer_payments": len(results["posted"]),
        "posted_vendor_payments": len(results["posted"]),
        "skipped": len(results["skipped"]),
        "failed": len(results["failed"]),
    }
    return results
