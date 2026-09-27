"""Zoho Books financial report requests."""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Mapping

from zoho.base_resource import BaseResource


class Reports(BaseResource):
    """Read financial reports from the Books API."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "reports")

    def general_ledger(
        self, *, from_date: str, to_date: str, rule: str,
        cash_based: bool = False,
    ) -> Mapping[str, Any]:
        """Fetch a rule-filtered General Ledger summary from the public API."""
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        try:
            requested_rule = json.loads(rule)
        except (TypeError, ValueError) as exc:
            raise ValueError("rule must be valid JSON") from exc
        if not isinstance(requested_rule, Mapping) or not requested_rule.get("columns"):
            raise ValueError("rule must include columns")
        response = self.client.request("GET", "reports/generalledger", params={
            "filter_by": "TransactionDate.CustomDate", "from_date": from_date,
            "to_date": to_date, "cash_based": str(cash_based).lower(), "rule": rule,
        })
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books General Ledger request failed")
        context = response.get("page_context")
        if not isinstance(context, Mapping) or any((
            context.get("from_date") != from_date,
            context.get("to_date") != to_date,
            context.get("cash_based") != str(cash_based).lower(),
            context.get("filter_by") != "TransactionDate.CustomDate",
        )):
            raise ValueError("Books General Ledger ignored requested dates or basis")
        applied = context.get("rule")
        requested_columns = requested_rule.get("columns")
        if (not isinstance(applied, Mapping)
                or applied.get("criteria_string") != requested_rule.get("criteria_string")
                or not isinstance(requested_columns, list)
                or not isinstance(applied.get("columns"), list)
                or len(applied["columns"]) != len(requested_columns)):
            raise ValueError("Books General Ledger did not apply the requested rule")
        for expected, actual in zip(requested_columns, applied["columns"]):
            if not isinstance(expected, Mapping) or not isinstance(actual, Mapping) or any(
                actual.get(key) != expected.get(key)
                for key in ("index", "field", "value", "comparator", "group")
            ):
                raise ValueError("Books General Ledger did not apply the requested rule")
        if not isinstance(response.get("generalledger"), list):
            raise ValueError("Books General Ledger rows are missing")
        return response

    def profit_and_loss_schedule_format(
        self,
        *,
        from_date: str,
        to_date: str,
        rule: str,
        cash_based: bool = False,
    ) -> Mapping[str, Any]:
        """Fetch schedule-format P&L figures through the public P&L endpoint.

        Books' web ``profitandloss-scheduleformat`` route is unavailable at the
        public API (code 5); the regular report accepts the same date and rule
        filters and returns the account totals needed by the statement.
        """
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        if not rule:
            raise ValueError("rule is required")
        response = self.client.request("GET", "reports/profitandloss", params={
            "filter_by": "TransactionDate.CustomDate",
            "from_date": from_date,
            "to_date": to_date,
            "cash_based": str(cash_based).lower(),
            "rule": rule,
            "show_rows": "all",
            "is_expand": "true",
        })
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books P&L request failed")
        context = response.get("page_context")
        if not isinstance(context, Mapping) or (
            context.get("from_date") != from_date
            or context.get("to_date") != to_date
            or context.get("cash_based") != str(cash_based).lower()
            or context.get("filter_by") != "TransactionDate.CustomDate"
        ):
            raise ValueError("Books P&L ignored the requested dates or basis")
        try:
            requested_rule = json.loads(rule)
        except (TypeError, ValueError) as exc:
            raise ValueError("rule must be valid JSON") from exc
        applied_rule = context.get("rule")
        if not isinstance(requested_rule, Mapping) or not isinstance(applied_rule, Mapping) or (
            applied_rule.get("criteria_string") != requested_rule.get("criteria_string")
        ):
            raise ValueError("Books P&L did not apply the branch rule")
        requested_columns = requested_rule.get("columns")
        applied_columns = applied_rule.get("columns")
        if not isinstance(requested_columns, list) or not isinstance(applied_columns, list) or len(requested_columns) != len(applied_columns):
            raise ValueError("Books P&L did not apply the branch rule")
        for requested, applied in zip(requested_columns, applied_columns):
            if not isinstance(requested, Mapping) or not isinstance(applied, Mapping) or any(
                applied.get(key) != requested.get(key)
                for key in ("index", "field", "value", "comparator", "group")
            ):
                raise ValueError("Books P&L did not apply the branch rule")
        return response
