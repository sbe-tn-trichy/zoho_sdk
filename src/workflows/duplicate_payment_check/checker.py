"""Find exact duplicate customer payments in Zoho Books."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


DuplicateKey = Tuple[str, date, Decimal]


def _date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _amount(value: Any) -> Optional[Decimal]:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def _payment_id(payment: Mapping[str, Any]) -> str:
    return str(payment.get("payment_id") or payment.get("customer_payment_id") or "").strip()


def _summary(payment: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "payment_id": _payment_id(payment),
        "payment_number": payment.get("payment_number"),
        "reference_number": payment.get("reference_number"),
        "date": payment.get("date"),
        "amount": payment.get("amount"),
        "customer_id": payment.get("customer_id"),
        "customer_name": payment.get("customer_name"),
        "payment_mode": payment.get("payment_mode"),
        "status": payment.get("status"),
    }


class DuplicatePaymentChecker:
    """Check Books customer payments without mutating any Books data."""

    def __init__(self, books_client: Any):
        self.books = books_client

    def run(
        self,
        *,
        customer_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = _date(from_date) if from_date else None
        end = _date(to_date) if to_date else None
        if from_date and not start:
            raise ValueError("from_date must use YYYY-MM-DD format.")
        if to_date and not end:
            raise ValueError("to_date must use YYYY-MM-DD format.")
        if start and end and start > end:
            raise ValueError("from_date cannot be later than to_date.")

        params: Dict[str, Any] = {}
        if customer_id:
            params["customer_id"] = customer_id
        if from_date:
            params["date_start"] = from_date
        if to_date:
            params["date_end"] = to_date

        # The live Books response uses the endpoint-shaped `customerpayments`
        # key (without an underscore), which is also BaseResource's default.
        payments = self.books.customer_payments.list_all(params=params or None)
        return self.check(payments, from_date=start, to_date=end)


    def check(
        self,
        payments: Iterable[Mapping[str, Any]],
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        payment_list = list(payments)
        grouped: Dict[DuplicateKey, List[Mapping[str, Any]]] = defaultdict(list)
        skipped: List[Dict[str, str]] = []
        considered = 0

        for original in payment_list:
            payment = dict(original)
            paid_on = _date(payment.get("date"))
            amount = _amount(payment.get("amount"))

            if not paid_on or amount is None:
                skipped.append({
                    "payment_id": _payment_id(payment),
                    "reason": "missing or invalid date/amount",
                })
                continue
            if (from_date and paid_on < from_date) or (to_date and paid_on > to_date):
                continue

            customer_id = str(payment.get("customer_id") or "").strip()
            payment_id = _payment_id(payment)
            if not customer_id and payment_id:
                try:
                    response = self.books.customer_payments.get(payment_id)
                    detail = response.get("payment") or response.get("customerpayment") or {}
                    payment.update(detail)
                    customer_id = str(payment.get("customer_id") or "").strip()
                except Exception as exc:
                    skipped.append({
                        "payment_id": payment_id,
                        "reason": f"could not retrieve customer ID: {exc}",
                    })
                    continue

            if not customer_id:
                skipped.append({
                    "payment_id": payment_id,
                    "reason": "missing customer ID",
                })
                continue

            considered += 1
            grouped[(customer_id, paid_on, amount)].append(payment)

        duplicate_groups: List[Dict[str, Any]] = []
        for (customer_id, paid_on, amount), matches in grouped.items():
            if len(matches) < 2:
                continue
            ordered = sorted(matches, key=lambda item: (_payment_id(item), str(item.get("payment_number") or "")))
            duplicate_groups.append({
                "customer_id": customer_id,
                "customer_name": next((item.get("customer_name") for item in ordered if item.get("customer_name")), None),
                "date": paid_on.isoformat(),
                "amount": format(amount, "f"),
                "payment_count": len(ordered),
                "payments": [_summary(item) for item in ordered],
            })

        duplicate_groups.sort(key=lambda item: (item["date"], item["customer_id"], Decimal(item["amount"])))
        return {
            "payments_scanned": len(payment_list),
            "payments_considered": considered,
            "duplicate_group_count": len(duplicate_groups),
            "duplicate_payment_count": sum(item["payment_count"] for item in duplicate_groups),
            "duplicate_groups": duplicate_groups,
            "skipped": skipped,
        }


def check_duplicate_payments(
    books_client: Any,
    *,
    customer_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience entry point for exact customer/date/amount duplicate checks."""
    return DuplicatePaymentChecker(books_client).run(
        customer_id=customer_id,
        from_date=from_date,
        to_date=to_date,
    )
