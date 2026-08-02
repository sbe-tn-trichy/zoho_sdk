"""Public vendor-ledger reconciliation API."""

from ..core.models import DotDict
from ._reconciler import (
    check_bill_ref,
    check_credit_ref,
    check_payment_ref,
    fetch_vendor_credits,
    reconcile_document_group,
    reconcile_vendor as _reconcile_vendor,
    reconcile_vendor_account as _reconcile_vendor_account,
)


def reconcile_vendor_account(*args, **kwargs) -> DotDict:
    return DotDict(_reconcile_vendor_account(*args, **kwargs))


def reconcile_vendor(*args, **kwargs) -> DotDict:
    return DotDict(_reconcile_vendor(*args, **kwargs))


__all__ = [
    "fetch_vendor_credits",
    "check_credit_ref",
    "check_bill_ref",
    "check_payment_ref",
    "reconcile_document_group",
    "reconcile_vendor_account",
    "reconcile_vendor",
]
