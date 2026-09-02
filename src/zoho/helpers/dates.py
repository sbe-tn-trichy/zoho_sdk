"""Date parsing and financial period calculation utilities for Zoho APIs."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Optional, Tuple


def parse_date(value: Any) -> Optional[date]:
    """Safely parse a date from ISO string, datetime, date object, or other common formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    # Try ISO YYYY-MM-DD
    try:
        return date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        pass

    # Try other common formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


def get_month_range(month: str) -> Tuple[date, date]:
    """Return the start and end date for a given YYYY-MM string."""
    try:
        parsed = datetime.strptime(month.strip(), "%Y-%m").date()
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid month {month!r}; expected YYYY-MM.") from exc
    last_day = calendar.monthrange(parsed.year, parsed.month)[1]
    return parsed.replace(day=1), parsed.replace(day=last_day)


def get_previous_month_range(as_of: Optional[date] = None) -> Tuple[date, date]:
    """Return the start and end date of the previous calendar month."""
    current = as_of or date.today()
    first_of_month = current.replace(day=1)
    previous_end = first_of_month - timedelta(days=1)
    return previous_end.replace(day=1), previous_end


def get_financial_year_range(
    as_of: Optional[date] = None,
    start_month: int = 4,
) -> Tuple[date, date]:
    """Return the start and end date of the financial/fiscal year.

    Defaults to the Indian financial year (April 1 to March 31).
    """
    if not 1 <= start_month <= 12:
        raise ValueError("start_month must be between 1 and 12.")

    ref_date = as_of or date.today()
    start_year = ref_date.year if ref_date.month >= start_month else ref_date.year - 1
    start = date(start_year, start_month, 1)
    end_year = start_year + 1 if start_month > 1 else start_year
    end_month = start_month - 1 if start_month > 1 else 12
    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return start, end

