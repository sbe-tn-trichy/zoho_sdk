"""Pure, bounded analysis of document number series."""

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence, TypedDict

from zoho.helpers.sequences import parse_doc_number
from .matching import parse_date


class NumberSeries(TypedDict):
    prefix: str
    kind: str
    count: int
    min_number: int | None
    max_number: int | None
    widths: list[int]
    duplicate_suffixes: list[int]
    missing_count: int
    missing_intervals: list[tuple[int, int]]
    intervals_truncated: bool
    start_date: str | None
    end_date: str | None
    samples: list[str]


def analyze_number_series(
    records: Sequence[Mapping[str, Any]], number_field: str, date_field: str,
    *, max_intervals: int = 100,
) -> list[NumberSeries]:
    """Group by raw prefix and report holes without enumerating suffix ranges."""
    if max_intervals < 0:
        raise ValueError("max_intervals cannot be negative")
    groups = defaultdict(list)
    for record in records:
        raw = str(record.get(number_field) or "").strip()
        prefix, suffix, width = parse_doc_number(raw)
        kind = "numeric" if width else "nonnumeric" if raw else "empty"
        groups[(prefix, kind)].append((raw, suffix, width, parse_date(record.get(date_field))))
    result = []
    for (prefix, kind), items in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        counts = Counter(suffix for _, suffix, width, _ in items if width)
        numbers = sorted(counts)
        intervals = []
        missing = 0
        total_intervals = 0
        for left, right in zip(numbers, numbers[1:]):
            if right > left + 1:
                missing += right - left - 1
                total_intervals += 1
                if len(intervals) < max_intervals:
                    intervals.append((left + 1, right - 1))
        dates = sorted(dt for *_, dt in items if dt is not None)
        result.append(NumberSeries(
            prefix=prefix, kind=kind, count=len(items), min_number=numbers[0] if numbers else None,
            max_number=numbers[-1] if numbers else None,
            widths=sorted({width for _, _, width, _ in items if width}),
            duplicate_suffixes=sorted(n for n, count in counts.items() if count > 1),
            missing_count=missing, missing_intervals=intervals,
            intervals_truncated=total_intervals > len(intervals),
            start_date=dates[0].isoformat() if dates else None,
            end_date=dates[-1].isoformat() if dates else None,
            samples=sorted({raw for raw, *_ in items})[:3],
        ))
    return result


__all__ = ["NumberSeries", "analyze_number_series", "parse_doc_number"]
