"""Read Zoho Books account registers as detailed general-ledger entries."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterator, Mapping, Sequence


class Registers:
    """Read the documented account-register report for one ledger account."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def list_transactions(
        self,
        account_id: str,
        *,
        from_date: str,
        to_date: str,
        page: int = 1,
        per_page: int = 200,
        cash_based: bool = False,
    ) -> Mapping[str, Any]:
        """Return one raw page from ``GET /registers/{account_id}/transactions``."""
        return self.list_transactions_for_accounts(
            [account_id], from_date=from_date, to_date=to_date, page=page,
            per_page=per_page, cash_based=cash_based,
        )

    def list_transactions_for_accounts(
        self,
        account_ids: Sequence[str],
        *,
        from_date: str,
        to_date: str,
        page: int = 1,
        per_page: int = 200,
        cash_based: bool = False,
    ) -> Mapping[str, Any]:
        """Return one register page filtered to up to 50 account IDs."""
        if isinstance(account_ids, (str, bytes)):
            raise ValueError("account_ids must be a sequence of IDs")
        ids = [str(account_id).strip() for account_id in account_ids]
        if not ids or any(not account_id for account_id in ids):
            raise ValueError("account_id is required")
        if len(ids) > 50 or len(set(ids)) != len(ids):
            raise ValueError("account_ids must be unique and contain at most 50 IDs")
        try:
            start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("from_date and to_date must be ISO dates") from exc
        if start > end:
            raise ValueError("from_date must not be after to_date")
        if page < 1 or per_page < 1:
            raise ValueError("page and per_page must be positive")
        response = self.client.request(
            "GET",
            f"registers/{ids[0]}/transactions",
            params={
                "account_id": ",".join(ids),
                "filter_by": "TransactionDate.CustomDate",
                "from_date": from_date,
                "to_date": to_date,
                "cash_based": str(cash_based).lower(),
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError("Books account register request failed")
        if not isinstance(response.get("register_transactions"), Mapping):
            raise ValueError("Books account register response is missing register_transactions")
        return response

    def iter_transactions(
        self,
        account_id: str,
        *,
        from_date: str,
        to_date: str,
        per_page: int = 200,
        cash_based: bool = False,
    ) -> Iterator[Mapping[str, Any]]:
        """Yield detailed transaction rows across all account-register pages."""
        yield from self.iter_transactions_for_accounts(
            [account_id], from_date=from_date, to_date=to_date,
            per_page=per_page, cash_based=cash_based,
        )

    def iter_transactions_for_accounts(
        self,
        account_ids: Sequence[str],
        *,
        from_date: str,
        to_date: str,
        per_page: int = 200,
        cash_based: bool = False,
    ) -> Iterator[Mapping[str, Any]]:
        """Yield detailed rows from one filtered register query across pages."""
        page = 1
        while True:
            response = self.list_transactions_for_accounts(
                account_ids,
                from_date=from_date,
                to_date=to_date,
                page=page,
                per_page=per_page,
                cash_based=cash_based,
            )
            register = response["register_transactions"]

            def walk(nodes: Any) -> Iterator[Mapping[str, Any]]:
                if not isinstance(nodes, list):
                    raise ValueError("Books account register has invalid account_transactions")
                for node in nodes:
                    if not isinstance(node, Mapping):
                        raise ValueError("Books account register has an invalid row")
                    if "account_transactions" in node:
                        yield from walk(node["account_transactions"])
                    elif "transaction_id" in node:
                        yield node

            yield from walk(register.get("account_transactions", []))
            context = response.get("page_context")
            if not isinstance(context, Mapping):
                raise ValueError("Books account register response is missing page_context")
            if not context.get("has_more_page"):
                return
            page += 1
