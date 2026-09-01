import logging
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from .config import Config

logger = logging.getLogger(__name__)

_ICICI_UPI_REFERENCE = re.compile(r"^\s*UPI/(\d{12})(?:/|$)", re.IGNORECASE)


def to_decimal(value: Any) -> Optional[Decimal]:
    """Safely coerce an arbitrary value or numeric string to a Decimal."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def to_text(value: Any) -> str:
    """Return a clean, stripped string representation of any value."""
    return str(value or "").strip()


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


def reconcile_rows(
    left_rows: Sequence[Dict[str, Any]],
    right_rows: Sequence[Dict[str, Any]],
    *,
    reference_matches: Callable[[Dict[str, Any], Dict[str, Any]], bool],
    date_tolerance_days: int,
    amount_tolerance: Any = Decimal("0"),
) -> Dict[str, Any]:
    """Conservatively reconcile parsed rows without relying on external IDs.

    Each row must contain ``date``, ``amount``, and ``raw``. A match is accepted
    only when the candidate relationship is unique on both sides. Ambiguous rows
    are reserved from later, weaker passes and returned for review.
    """
    if date_tolerance_days < 0:
        raise ValueError("date_tolerance_days cannot be negative")
    tolerance = to_decimal(amount_tolerance)
    if tolerance is None or tolerance < 0:
        raise ValueError("amount_tolerance must be a non-negative number")

    left = list(left_rows)
    right = list(right_rows)
    matched_left: Set[int] = set()
    matched_right: Set[int] = set()
    ambiguous_left: Set[int] = set()
    ambiguous_right: Set[int] = set()
    result: Dict[str, Any] = {
        "exact_matches": [],
        "strong_matches": [],
        "weak_matches": [],
        "ambiguous_matches": [],
    }

    def eligible_amount(row: Dict[str, Any]) -> Optional[Decimal]:
        amount = to_decimal(row.get("amount"))
        return abs(amount) if amount is not None else None

    def candidates_for(pass_name: str) -> Dict[int, List[int]]:
        candidates: Dict[int, List[int]] = {}
        for left_index, left_row in enumerate(left):
            if left_index in matched_left or left_index in ambiguous_left:
                continue
            left_date = left_row.get("date")
            left_amount = eligible_amount(left_row)
            if left_date is None or left_amount is None:
                continue
            for right_index, right_row in enumerate(right):
                if right_index in matched_right or right_index in ambiguous_right:
                    continue
                right_date = right_row.get("date")
                right_amount = eligible_amount(right_row)
                if right_date is None or right_amount is None:
                    continue
                if abs((left_date - right_date).days) > date_tolerance_days:
                    continue
                difference = abs(left_amount - right_amount)
                if pass_name == "exact":
                    valid = difference == 0 and reference_matches(left_row, right_row)
                elif pass_name == "strong":
                    valid = difference == 0
                else:
                    valid = Decimal("0") < difference <= tolerance
                if valid:
                    candidates.setdefault(left_index, []).append(right_index)
        return candidates

    for pass_name, result_key in (
        ("exact", "exact_matches"),
        ("strong", "strong_matches"),
        ("weak", "weak_matches"),
    ):
        if pass_name == "weak" and tolerance == 0:
            continue
        candidates = candidates_for(pass_name)
        right_to_left: Dict[int, List[int]] = {}
        for left_index, right_indexes in candidates.items():
            for right_index in right_indexes:
                right_to_left.setdefault(right_index, []).append(left_index)
        accepted = [
            (left_index, right_indexes[0])
            for left_index, right_indexes in candidates.items()
            if len(right_indexes) == 1
            and len(right_to_left.get(right_indexes[0], [])) == 1
        ]
        for left_index, right_index in accepted:
            result[result_key].append(
                (left[left_index]["raw"], right[right_index]["raw"])
            )
            matched_left.add(left_index)
            matched_right.add(right_index)

        accepted_left = {left_index for left_index, _ in accepted}
        accepted_right = {right_index for _, right_index in accepted}
        for left_index, right_indexes in candidates.items():
            remaining = [
                right_index for right_index in right_indexes
                if right_index not in accepted_right
            ]
            if left_index in accepted_left or not remaining:
                continue
            ambiguous_left.add(left_index)
            ambiguous_right.update(remaining)
            result["ambiguous_matches"].append(
                {
                    "pass": pass_name,
                    "left": left[left_index]["raw"],
                    "candidates": [right[index]["raw"] for index in remaining],
                }
            )

    result.update(
        matched_left_indices=matched_left,
        matched_right_indices=matched_right,
        ambiguous_left_indices=ambiguous_left,
        ambiguous_right_indices=ambiguous_right,
    )
    return result
