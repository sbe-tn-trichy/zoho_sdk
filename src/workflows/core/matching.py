"""Low-level, pure helpers shared by matching workflows."""
import logging
import re
from datetime import datetime, date
from typing import Any, Dict, Optional

from .config import Config

logger = logging.getLogger(__name__)

_ICICI_UPI_REFERENCE = re.compile(r"^\s*UPI/(\d{12})(?:/|$)", re.IGNORECASE)


def parse_date(date_str: Any) -> Optional[date]:
    """Safely parse various date formats into a datetime.date object."""
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        return date_str.date()
    if isinstance(date_str, date):
        return date_str
    value = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.split("T")[0]).date()
    except ValueError:
        return None


def get_abs_amount(tx: Dict[str, Any]) -> float:
    """Extract absolute amount from a bank transaction dict."""
    try:
        return abs(float(tx.get("amount", 0.0)))
    except (ValueError, TypeError):
        return 0.0


def get_bank_reference(tx: Dict[str, Any], bank_account_id: str) -> Any:
    """Return the reconciliation reference for a Books bank transaction.

    ICICI statement imports expose a short statement reference in
    ``reference_number`` while the actual 12-digit UPI reference is the first
    component of the transaction description. Other transaction types and
    bank accounts retain the Zoho-provided reference fallback order.
    """
    if str(bank_account_id) == str(Config.BANK_ACCOUNT_ICICI):
        match = _ICICI_UPI_REFERENCE.match(str(tx.get("description") or ""))
        if match:
            return match.group(1)
    return tx.get("reference_number") or tx.get("reference") or tx.get("cheque_number")


def ref_match(ref1: Any, ref2: Any) -> bool:
    """Compare two reference numbers case-insensitively and stripped of whitespace."""
    r1 = str(ref1 or "").strip().lower()
    r2 = str(ref2 or "").strip().lower()
    return bool(r1 and r2 and r1 == r2)
