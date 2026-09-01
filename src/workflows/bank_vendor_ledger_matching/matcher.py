"""Public bank-to-vendor-ledger matching API."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core.matching import get_abs_amount, get_bank_reference, parse_date, ref_match
from ..core.models import DotDict
from ._matcher import match_bank_with_vendor_ledger as _match_bank_with_vendor_ledger
from ._matcher import match_ledger_entries as _match_ledger_entries


def match_ledger_entries(
    books_client: Any,
    bank_account_id: str,
    vendor_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    date_tolerance_days: int = 4,
    amount_tolerance: float = 0.01,
) -> DotDict:
    """Match Zoho Books bank withdrawals against Books vendor payments."""
    return DotDict(_match_ledger_entries(
        books_client=books_client,
        bank_account_id=bank_account_id,
        vendor_id=vendor_id,
        start_date=start_date,
        end_date=end_date,
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
    ))


def match_bank_with_vendor_ledger(
    books_client: Any,
    bank_account_id: str,
    vendor_ledger_path: str,
    vendor_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    date_tolerance_days: int = 4,
    amount_tolerance: float = 0.01,
) -> DotDict:
    """Match Zoho Books bank withdrawals against a cleaned external vendor ledger file."""
    return DotDict(_match_bank_with_vendor_ledger(
        books_client=books_client,
        bank_account_id=bank_account_id,
        vendor_ledger_path=vendor_ledger_path,
        vendor_id=vendor_id,
        start_date=start_date,
        end_date=end_date,
        date_tolerance_days=date_tolerance_days,
        amount_tolerance=amount_tolerance,
    ))


__all__ = [
    "parse_date",
    "get_abs_amount",
    "get_bank_reference",
    "ref_match",
    "match_ledger_entries",
    "match_bank_with_vendor_ledger",
]
