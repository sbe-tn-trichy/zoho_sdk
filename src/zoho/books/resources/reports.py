"""Zoho Books financial report requests."""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Iterator, Mapping, Sequence

from zoho.base_resource import BaseResource


class Reports(BaseResource):
    """Read financial reports from the Books API."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "reports")

    def account_transactions(
        self, account_ids: Sequence[str], *, from_date: str, to_date: str,
        page: int = 1, per_page: int = 500, cash_based: bool = False,
        response_option: int = 0,
    ) -> Mapping[str, Any]:
        """Read account ledger rows (option 0) or count metadata (option 2).

        Preserve raw transaction groups, balance rows, and page context. Dates
        are required because omitting them can select the current month.
        """
        if isinstance(account_ids, (str, bytes)):
            raise ValueError("account_ids must be a sequence of IDs")
        ids = list(account_ids)
        if (not ids or any(not isinstance(value, str) or not value.strip() for value in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("account_ids must contain unique non-empty IDs")
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        if (type(page) is not int or page < 1 or type(per_page) is not int
                or not 1 <= per_page <= 500):
            raise ValueError("page must be positive and per_page must be between 1 and 500")
        if not isinstance(cash_based, bool):
            raise ValueError("cash_based must be a boolean")
        if type(response_option) is not int or response_option not in (0, 2):
            raise ValueError("response_option must be 0 (rows) or 2 (count)")
        fields = ("date", "account_name", "transaction_details", "transaction_type",
                  "entity_number", "reference_number", "debit", "credit",
                  "net_amount", "running_balance")
        rule = {"columns": [{"index": 1, "field": "account_id", "value": ids,
                             "comparator": "in", "group": "report"}],
                "criteria_string": "1"}
        response = self.client.request("GET", "reports/accounttransaction", params={
            "page": page, "per_page": per_page, "cash_based": str(cash_based).lower(),
            "from_date": from_date, "to_date": to_date,
            "filter_by": "TransactionDate.CustomDate", "rule": json.dumps(rule),
            "group_by": json.dumps([{"field": "none", "group": "report"}]),
            "select_columns": json.dumps(
                [{"field": field, "group": "report"} for field in fields]
                + [{"field": "location_name", "group": "branch"}]),
            "show_sub_account": "false", "usestate": "false",
            "is_new_flow": "false", "response_option": response_option,
        })
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books Account Transactions request failed")
        context = response.get("page_context")
        if not isinstance(context, Mapping) or any((
            context.get("page") != page, context.get("from_date") != from_date,
            context.get("to_date") != to_date,
            context.get("cash_based") != str(cash_based).lower(),
            context.get("filter_by") != "TransactionDate.CustomDate",
        )):
            raise ValueError("Books Account Transactions ignored requested scope or page")
        applied = context.get("rule")
        if (not isinstance(applied, Mapping) or applied.get("criteria_string") != "1"
                or not isinstance(applied.get("columns"), list)
                or len(applied["columns"]) != 1
                or not isinstance(applied["columns"][0], Mapping)
                or any(applied["columns"][0].get(key) != value
                       for key, value in rule["columns"][0].items())):
            raise ValueError("Books Account Transactions ignored requested account rule")
        if response_option == 0:
            if (not isinstance(response.get("account_transactions"), list)
                    or type(context.get("has_more_page")) is not bool):
                raise ValueError("Books Account Transactions has invalid rows or pagination")
        elif any(type(context.get(key)) is not int or context[key] < 0
                 for key in ("total", "total_pages")):
            raise ValueError("Books Account Transactions has invalid count metadata")
        return response

    def trial_balance(
        self, *, from_date: str, to_date: str, rule: str | None = None,
        cash_based: bool = False, show_rows: str = "non_zero",
    ) -> Mapping[str, Any]:
        """Fetch opening, debit, credit and closing balances for a date range.

        Preserve the raw response, including Dr/Cr formatting and report groups.
        Authentication and organization scope come from the SDK client.
        """
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        if not isinstance(cash_based, bool):
            raise ValueError("cash_based must be a boolean")
        if show_rows not in ("all", "non_zero"):
            raise ValueError("show_rows must be all or non_zero")
        requested_rule = None
        if rule is not None:
            try:
                requested_rule = json.loads(rule)
            except (TypeError, ValueError) as exc:
                raise ValueError("rule must be valid JSON") from exc
            if (not isinstance(requested_rule, Mapping)
                    or not isinstance(requested_rule.get("columns"), list)
                    or not requested_rule["columns"]
                    or any(not isinstance(column, Mapping) for column in requested_rule["columns"])):
                raise ValueError("rule must include column objects")
        fields = ("name", "opening_balance", "net_debit", "net_credit", "closing_balance")
        params = {
            "cash_based": str(cash_based).lower(), "filter_by": "TransactionDate.CustomDate",
            "from_date": from_date, "to_date": to_date,
            "select_columns": json.dumps([{"field": field, "group": "report"} for field in fields]),
            "is_for_date_range": "true", "show_rows": show_rows,
            "sort_column": "name", "sort_order": "A", "usestate": "true",
            "amount_format": "dr_cr", "is_response_new_flow": "true", "response_option": 1,
        }
        if rule is not None:
            params["rule"] = rule
        response = self.client.request("GET", "reports/trialbalance", params=params)
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books Trial Balance request failed")
        context = response.get("page_context")
        if not isinstance(context, Mapping) or any((
            context.get("from_date") != from_date, context.get("to_date") != to_date,
            context.get("cash_based") != str(cash_based).lower(),
        )):
            raise ValueError("Books Trial Balance ignored requested dates or basis")
        if requested_rule is not None:
            applied = context.get("rule")
            if (not isinstance(applied, Mapping)
                    or applied.get("criteria_string") != requested_rule.get("criteria_string")
                    or not isinstance(applied.get("columns"), list)
                    or len(applied["columns"]) != len(requested_rule["columns"])):
                raise ValueError("Books Trial Balance did not apply the requested rule")
            for expected, actual in zip(requested_rule["columns"], applied["columns"]):
                if not isinstance(actual, Mapping) or any(
                    actual.get(key) != expected.get(key)
                    for key in ("index", "field", "value", "comparator", "group")
                ):
                    raise ValueError("Books Trial Balance did not apply the requested rule")
        return response

    def general_ledger_details(
        self, account_ids: Sequence[str], *, from_date: str, to_date: str,
        page: int = 1, per_page: int = 500, cash_based: bool = False,
    ) -> Mapping[str, Any]:
        """Return one raw Detailed General Ledger page, preserving report groups.

        Uses the ``generalledgerdetails`` endpoint captured from Books' web app.
        OAuth availability depends on the configured Books API deployment.
        """
        if isinstance(account_ids, (str, bytes)):
            raise ValueError("account_ids must be a sequence of IDs")
        ids = list(account_ids)
        if (not ids or any(not isinstance(value, str) or not value.strip() for value in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("account_ids must contain unique non-empty IDs")
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        if (type(page) is not int or page < 1 or type(per_page) is not int
                or not 1 <= per_page <= 500):
            raise ValueError("page must be positive and per_page must be between 1 and 500")
        if not isinstance(cash_based, bool):
            raise ValueError("cash_based must be a boolean")
        fields = ("date", "account_name", "transaction_details", "transaction_type",
                  "entity_number", "reference_number", "debit", "credit", "net_amount")
        rule = {"columns": [{"index": 1, "field": "account_id", "value": ids,
                             "comparator": "in", "group": "report"}],
                "criteria_string": "1"}
        response = self.client.request("GET", "reports/generalledgerdetails", params={
            "page": page, "per_page": per_page, "sort_column": "date", "sort_order": "A",
            "cash_based": str(cash_based).lower(),
            "filter_by": "TransactionDate.CustomDate", "from_date": from_date,
            "to_date": to_date, "rule": json.dumps(rule),
            "group_by": json.dumps([{"field": "account_name", "group": "report"}]),
            "select_columns": json.dumps([{"field": field, "group": "report"} for field in fields]),
            "show_sub_account": "false", "usestate": "true", "is_new_flow": "false",
            "show_tags": "false", "response_option": 0,
        })
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books Detailed General Ledger request failed")
        context = response.get("page_context")
        if not isinstance(context, Mapping) or type(context.get("has_more_page")) is not bool:
            raise ValueError("Books Detailed General Ledger has invalid page_context")
        if "page" in context and context["page"] != page:
            raise ValueError("Books Detailed General Ledger returned the wrong page")
        return response

    def iter_general_ledger_details_pages(
        self, account_ids: Sequence[str], *, from_date: str, to_date: str,
        per_page: int = 500, cash_based: bool = False, max_pages: int = 100,
    ) -> Iterator[Mapping[str, Any]]:
        """Yield raw report pages; stop on repeated content or the request bound.

        Raise rather than silently return an incomplete report at ``max_pages``.
        Transaction groups are preserved until a live response schema is verified.
        """
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            response = self.general_ledger_details(
                account_ids, from_date=from_date, to_date=to_date, page=page,
                per_page=per_page, cash_based=cash_based,
            )
            payload = {key: value for key, value in response.items()
                       if key not in ("page_context", "code", "message")}
            signature = json.dumps(payload, sort_keys=True)
            if signature in seen:
                raise ValueError("Books Detailed General Ledger repeated a page")
            seen.add(signature)
            yield response
            if not response["page_context"]["has_more_page"]:
                return
        raise ValueError("Books Detailed General Ledger exceeded max_pages")

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
