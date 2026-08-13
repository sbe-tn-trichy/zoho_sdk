"""Public bank-reconciliation API."""
from ..core.models import DotDict
from ..core.matching import get_bank_reference, parse_date, get_abs_amount, ref_match
from ._matcher import match_ledger_entries as _match_ledger_entries
from ._matcher import match_bank_with_vendor_ledger as _match_bank_with_vendor_ledger

def match_ledger_entries(*args, **kwargs) -> DotDict:
    return DotDict(_match_ledger_entries(*args, **kwargs))

def match_bank_with_vendor_ledger(*args, **kwargs) -> DotDict:
    return DotDict(_match_bank_with_vendor_ledger(*args, **kwargs))

__all__ = [
    "parse_date",
    "get_abs_amount",
    "get_bank_reference",
    "ref_match",
    "match_ledger_entries",
    "match_bank_with_vendor_ledger",
]
