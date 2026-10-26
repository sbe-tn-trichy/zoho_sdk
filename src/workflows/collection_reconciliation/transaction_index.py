"""Run-local bank candidates indexed without weakening amount/date tolerances."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ..core.exceptions import ReconciliationError
from ..core.matching import get_bank_reference, parse_date, to_decimal
from .identifiers import identifier


@dataclass(frozen=True)
class BankCandidate:
    row: Mapping[str, Any]
    transaction_id: str
    amount: Decimal
    reference: str
    narration: str


class TransactionIndex:
    """Normalize once, then search occupied dates and sorted absolute amounts."""

    def __init__(self, transactions: Sequence[Mapping[str, Any]], bank_account_id: str):
        by_day: dict[int, list[BankCandidate]] = defaultdict(list)
        for row in transactions:
            transaction_id = identifier(row, ("transaction_id", "id"))
            day = parse_date(row.get("date") or row.get("transaction_date"))
            amount = to_decimal(row.get("amount"))
            if not transaction_id or not day or amount is None:
                continue
            if not amount.is_finite():
                raise ReconciliationError(f"Bank transaction {transaction_id} has a non-finite amount.")
            by_day[day.toordinal()].append(BankCandidate(
                row, transaction_id, abs(amount),
                str(get_bank_reference(row, bank_account_id) or "").strip().casefold(),
                str(row.get("description") or row.get("narration") or "").strip().casefold(),
            ))
        self._days = sorted(by_day)
        self._by_day = {day: sorted(rows, key=lambda row: row.amount)
                        for day, rows in by_day.items()}

    def candidates(self, day: date, amount: Decimal, date_tolerance: int,
                   amount_tolerance: Decimal) -> list[BankCandidate]:
        ordinal = day.toordinal()
        first = bisect_left(self._days, ordinal - date_tolerance)
        last = bisect_right(self._days, ordinal + date_tolerance)
        result = []
        for bank_day in self._days[first:last]:
            rows = self._by_day[bank_day]
            low = bisect_left(rows, abs(amount) - amount_tolerance, key=lambda row: row.amount)
            high = bisect_right(rows, abs(amount) + amount_tolerance, key=lambda row: row.amount)
            result.extend(rows[low:high])
        return result
