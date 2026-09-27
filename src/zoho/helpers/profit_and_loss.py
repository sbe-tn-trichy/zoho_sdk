"""Convenience wrapper for the branch-scoped schedule-format P&L."""

from __future__ import annotations

import json
from typing import Any, Mapping


def fetch_profit_and_loss_schedule_format(
    books_client: Any,
    *,
    from_date: str,
    to_date: str,
    excluded_location_id: str,
) -> Mapping[str, Any]:
    """Fetch an accrual P&L excluding one Books branch by location ID."""
    if not excluded_location_id or not excluded_location_id.strip():
        raise ValueError("excluded_location_id is required")
    rule = json.dumps({
        "columns": [{
            "index": 1,
            "field": "location_name",
            "value": [excluded_location_id.strip()],
            "comparator": "not_in",
            "group": "branch",
        }],
        "criteria_string": "1",
    }, separators=(",", ":"))
    return books_client.reports.profit_and_loss_schedule_format(
        from_date=from_date,
        to_date=to_date,
        cash_based=False,
        rule=rule,
    )
