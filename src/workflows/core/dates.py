"""Strict Indian financial-year selection using SDK calendar primitives."""

from datetime import date, datetime
import re

from zoho.helpers.dates import get_financial_year_range


def get_fy_date_range(
    fy_param: str, reference_date: date | None = None,
) -> tuple[date, date, str]:
    """Resolve aliases, start years, or consecutive FY pairs to inclusive dates."""
    ref = reference_date or date.today()
    if isinstance(ref, datetime):
        ref = ref.date()
    current = get_financial_year_range(ref)[0].year
    value = fy_param.strip().lower()
    if value in {"last", "prev", "previous", "last_fy", "last-fy"}:
        year = current - 1
    elif value in {"current", "this", "this_fy", "current_fy"}:
        year = current
    else:
        match = re.fullmatch(r"(\d{2}|\d{4})[-/](\d{2}|\d{4})", value)
        if match:
            first, last = match.groups()
            year = int(first) + (2000 if len(first) == 2 else 0)
            expected = str(year + 1) if len(last) == 4 else f"{(year + 1) % 100:02d}"
            if last != expected:
                raise ValueError("Financial-year endpoints must be consecutive")
        elif re.fullmatch(r"\d{4}", value):
            numeric = int(value)
            if 1900 <= numeric <= 2098:
                year = numeric
            elif int(value[2:]) == (int(value[:2]) + 1) % 100:
                year = 2000 + int(value[:2])
            else:
                raise ValueError("Invalid financial year")
        else:
            raise ValueError("Expected a financial-year alias, start year, or consecutive pair")
    if not 1900 <= year <= 2098:
        raise ValueError("Supported financial-year start years are 1900 through 2098")
    start, end = get_financial_year_range(date(year, 4, 1))
    return start, end, f"{year}-{(year + 1) % 100:02d}"


__all__ = ["get_fy_date_range"]
