"""Typed data contracts for collection reconciliation and payment review."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, TypedDict


class InvoiceAllocation(TypedDict, total=False):
    """Allocation of a customer payment to a specific invoice."""

    invoice_id: str
    invoice_number: str
    amount_applied: Decimal
    balance: Decimal
    due_date: str


class ChequeDetail(TypedDict, total=False):
    """Normalized cheque record joined from Creator All_Cheque_Details."""

    record_id: str
    cheque_number: str
    customer_id: str
    presented_date: str
    amount: Decimal


class PaymentProposal(TypedDict, total=False):
    """Proposal uniting a Creator collection row with bank line & invoice preview."""

    id: str
    fingerprint: str
    payment_type: str
    creator: Dict[str, Any]
    bank: Optional[Dict[str, Any]]
    bank_name: str
    bank_account_id: str
    reviewable: bool
    reason: str
    decision: str
    push_status: str
    books_payment_id: str
    books_payment_number: str
    invoice_allocations: List[InvoiceAllocation]
    unallocated_amount: Decimal
    allocation_error: str
    error: str
