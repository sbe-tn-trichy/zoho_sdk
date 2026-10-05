"""Stable records for PDF evidence, audit findings and reviewed corrections."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class RmaCreditPolicy:
    vendor_id: str
    customer_id: str
    rma_item_id: str
    rma_account_id: str
    clearing_account_id: str
    against_invoice_field: str = 'cf_against_invoice'
    rounding_tolerance: Decimal = Decimal('1.00')

    def __post_init__(self) -> None:
        for value in (self.vendor_id, self.customer_id, self.rma_item_id,
                      self.rma_account_id, self.clearing_account_id):
            if not value or not value.isdigit():
                raise ValueError('Policy requires explicit numeric Books/Inventory IDs')
        if not self.rounding_tolerance.is_finite() or self.rounding_tolerance < 0:
            raise ValueError('Rounding tolerance must be finite and nonnegative')


@dataclass(frozen=True)
class CreditMemoEvidence:
    supplier_number: str
    printed_number: str
    date: date
    amount: Decimal
    rso_number: str
    invoice_number: str
    is_return: bool
    document_id: str = ''
    source_path: str = ''


@dataclass(frozen=True)
class CreditFinding:
    code: str
    message: str
    blocking: bool = False


@dataclass
class CreditAudit:
    credit: dict[str, Any]
    memos: tuple[CreditMemoEvidence, ...]
    journal: dict[str, Any] | None
    payment: dict[str, Any] | None
    findings: list[CreditFinding]
    journal_link: str = ''
    payment_link: str = ''

    @property
    def is_rma(self) -> bool:
        return any(m.is_return for m in self.memos)

    @property
    def correction_allowed(self) -> bool:
        return self.is_rma and not any(f.blocking for f in self.findings)


@dataclass(frozen=True)
class CreditCorrectionPlan:
    policy: RmaCreditPolicy
    audit: CreditAudit
    payloads: dict[str, dict[str, Any]]


@dataclass
class CreditCorrectionResult:
    vendor_credit_id: str
    dry_run: bool
    status: Literal['preview', 'submitting', 'verified', 'failed'] = 'preview'
    completed: list[str] = field(default_factory=list)
    pending: str = ''
    error: str = ''
    after: dict[str, dict[str, Any]] = field(default_factory=dict)


class CreditCorrectionError(RuntimeError):
    """A failed/uncertain mutation; result records completed and pending operations."""
    def __init__(self, message: str, result: CreditCorrectionResult):
        super().__init__(message)
        self.result = result
