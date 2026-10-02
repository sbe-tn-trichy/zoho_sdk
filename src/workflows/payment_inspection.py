"""Analytics customer-payment inspection, with pure period and series analysis."""
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Dict, List, Mapping, Sequence, TypedDict
from .core.matching import parse_date
from .core.sequences import analyze_number_series, parse_doc_number

def fetch_customer_payments(analytics: Any, workspace_id: str) -> List[Dict[str, Any]]:
    """Query customer payments from Zoho Analytics."""
    query = """
    SELECT 
        "Payment Number",
        "Payment Date",
        "Payment Mode",
        "Payment Status",
        "Amount (BCY)",
        "Location ID"
    FROM "Customer Payments (Zoho Books)"
    """
    return analytics.queries.execute(
        workspace_id=workspace_id,
        sql_query=query,
        max_attempts=30,
        poll_interval=2.0,
    )


class PaymentSeriesSummary(TypedDict):
    series_prefix: str
    raw_prefix: str
    count: int
    min_number: int | None
    max_number: int | None
    number_range: str
    digit_padding: str
    start_date: str
    end_date: str
    date_range: str
    sample_first: str
    sample_last: str
    top_modes: str
    observed_widths: list[int]
    duplicate_suffixes: list[int]
    missing_count: int
    missing_intervals: list[tuple[int, int]]
    intervals_truncated: bool


def extract_series_info(
    records: Sequence[Mapping[str, Any]], start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[PaymentSeriesSummary], int]:
    """Filter calendar dates and preserve CLI report fields with bounded gap metadata."""
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date exceeds end_date")
    filtered = []
    grouped = defaultdict(list)
    for record in records:
        day = parse_date(record.get("Payment Date"))
        if (start_date or end_date) and day is None:
            continue
        if start_date and day < start_date or end_date and day > end_date:
            continue
        filtered.append(record)
        number = str(record.get("Payment Number") or "").strip()
        prefix, _, width = parse_doc_number(number)
        kind = "numeric" if width else "nonnumeric" if number else "empty"
        grouped[(prefix, kind)].append(record)
    summaries = []
    for row in analyze_number_series(filtered, "Payment Number", "Payment Date"):
        prefix, kind = row["prefix"], row["kind"]
        items = grouped[(prefix, kind)]
        numbers = sorted(str(item.get("Payment Number") or "").strip() for item in items)
        minimum, maximum = row["min_number"], row["max_number"]
        widths = row["widths"]
        width = max(widths, default=0)
        number_range = f"{minimum:0{width}d} - {maximum:0{width}d}" if minimum is not None else "Non-numeric"
        first_day = date.fromisoformat(row["start_date"]).strftime("%d/%m/%Y") if row["start_date"] else "N/A"
        last_day = date.fromisoformat(row["end_date"]).strftime("%d/%m/%Y") if row["end_date"] else "N/A"
        modes = Counter(str(item.get("Payment Mode") or "Unknown") for item in items)
        mode_counts = sorted(modes.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        summaries.append(PaymentSeriesSummary(
            series_prefix="[EMPTY]" if kind == "empty" else prefix or "[Numeric Only]",
            raw_prefix="[EMPTY]" if kind == "empty" else prefix,
            count=row["count"], min_number=minimum, max_number=maximum,
            number_range=number_range,
            digit_padding=f"{width} digits" if width else "N/A",
            start_date=first_day, end_date=last_day,
            date_range=f"{first_day} to {last_day}" if row["start_date"] else "N/A",
            sample_first=numbers[0], sample_last=numbers[-1],
            top_modes=", ".join(f"{mode} ({count})" for mode, count in mode_counts),
            observed_widths=widths, duplicate_suffixes=row["duplicate_suffixes"],
            missing_count=row["missing_count"], missing_intervals=row["missing_intervals"],
            intervals_truncated=row["intervals_truncated"],
        ))
    return summaries, len(filtered)


__all__ = ["PaymentSeriesSummary", "fetch_customer_payments", "extract_series_info"]
