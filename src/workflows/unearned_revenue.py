"""Read-only discovery of customer payments with unused balances."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import time
import re

from .core.exceptions import ReconciliationError
from .core.matching import to_finite_decimal, to_text

DEFAULT_UNEARNED_ACCOUNT_ID = "1094368000000000617"


@dataclass(frozen=True)
class UnusedPayment:
    payment_id: str
    payment_number: str
    customer_id: str
    customer_name: str
    date: str
    currency_code: str
    amount: Decimal
    unused_amount: Decimal


@dataclass
class UnearnedRevenueReview:
    account_id: str
    account_name: str
    payments_checked: int
    payments: list[UnusedPayment]
    totals_by_currency: dict[str, Decimal]
    limitations: list[str]


def find_unused_customer_payments(
    books: Any, *, account_id: str = DEFAULT_UNEARNED_ACCOUNT_ID,
    request_interval: float = 0.5,
) -> UnearnedRevenueReview:
    """Scan all payment details for current unused amounts, without date filters.

    These are candidates for the selected liability account, not proven ledger
    postings. No allocations or accounting records are changed.
    """
    if not account_id.isdigit() or request_interval < 0:
        raise ValueError("A numeric account ID and nonnegative request interval are required")
    response = books.chart_of_accounts.get(account_id)
    account = response.get("chart_of_account")
    if response.get("code") != 0 or not isinstance(account, dict):
        raise ReconciliationError(f"Cannot read account {account_id}")
    if to_text(account.get("account_id")) != account_id:
        raise ReconciliationError("Account detail identity mismatch")
    name = to_text(account.get("account_name"))
    if not name or "unearned" not in name.lower():
        raise ReconciliationError(f"Account {account_id} is not named as an unearned revenue account: {name!r}")
    seen: set[str] = set()
    rows: list[UnusedPayment] = []
    totals: dict[str, Decimal] = {}
    for summary in books.customer_payments.list_all():
        identifier = to_text(summary.get("payment_id"))
        if not identifier or identifier in seen:
            raise ReconciliationError("Missing or duplicate customer payment ID")
        seen.add(identifier)
        time.sleep(request_interval)
        response = books.customer_payments.get(identifier)
        payment = response.get("payment")
        if response.get("code") != 0 or not isinstance(payment, dict):
            raise ReconciliationError(f"Cannot read payment {identifier}")
        if to_text(payment.get("payment_id")) != identifier:
            raise ReconciliationError(f"Payment detail identity mismatch: {identifier}")
        customer_id = to_text(payment.get("customer_id"))
        if not customer_id or (summary.get("customer_id") and to_text(summary["customer_id"]) != customer_id):
            raise ReconciliationError(f"Payment customer identity mismatch: {identifier}")
        amounts = {}
        for field in ("amount", "unused_amount"):
            value = to_finite_decimal(payment.get(field), allow_commas=True)
            if value is None or value < 0:
                raise ReconciliationError(f"Payment {identifier}: invalid or missing {field}")
            amounts[field] = value
        if amounts["unused_amount"] > amounts["amount"]:
            raise ReconciliationError(f"Payment {identifier}: unused amount exceeds payment amount")
        if not amounts["unused_amount"]:
            continue
        currency = to_text(payment.get("currency_code"))
        if not currency:
            raise ReconciliationError(f"Payment {identifier}: missing currency_code")
        rows.append(UnusedPayment(identifier, to_text(payment.get("payment_number")),
            customer_id, to_text(payment.get("customer_name")), to_text(payment.get("date")),
            currency, amounts["amount"], amounts["unused_amount"]))
        totals[currency] = totals.get(currency, Decimal(0)) + amounts["unused_amount"]
    return UnearnedRevenueReview(account_id, name, len(seen),
        sorted(rows, key=lambda row: (row.customer_name, row.date, row.payment_id)), totals,
        ["Current unused customer payments are candidates; payment details do not prove association with this liability account.",
         "Totals are in payment currencies, not a reconciliation to the account's base-currency ledger balance.",
         "Credit notes, journals and other liability postings are outside this payment scan. Zero candidates do not prove a zero account balance.",
         "Sequential live reads are not an atomic snapshot; rerun after correcting allocations."])


def review_unearned_revenue_analytics(
    analytics: Any, *, workspace_id: str, account_id: str = DEFAULT_UNEARNED_ACCOUNT_ID,
) -> dict[str, Any]:
    """Read unused payments and all account postings through Analytics SQL.

    Joins are performed after aggregation to avoid multiplying ledger amounts.
    Entity ID matches are exposed as evidence rather than assumed allocations.
    """
    if not account_id.isdigit() or not workspace_id.isdigit():
        raise ValueError("Numeric workspace and account IDs are required")
    queries = {
        "account": f'''SELECT "Account ID", "Account Name" FROM "Accounts (Zoho Books)"
            WHERE "Account ID" = '{account_id}' ''',
        "payments": '''SELECT p."Payment ID" AS "Payment ID", p."Payment Number" AS "Payment Number", p."Payment Date" AS "Payment Date",
            p."Customer ID" AS "Customer ID", c."Customer Name" AS "Customer Name", p."Currency Code" AS "Currency Code", p."Payment Status" AS "Payment Status",
            p."Amount (BCY)" AS "Amount (BCY)", p."Unused Amount (BCY)" AS "Unused Amount (BCY)", p."Unused Amount (FCY)" AS "Unused Amount (FCY)",
            p."Location ID" AS "Location ID", p."Last Modified Time" AS "Last Modified Time"
            FROM "Customer Payments (Zoho Books)" p
            LEFT JOIN "Customers (Zoho Books)" c ON p."Customer ID" = c."Customer ID"
            WHERE p."Unused Amount (BCY)" > 0 OR p."Unused Amount (BCY)" IS NULL''',
        "postings": f'''SELECT "Entity ID", "Entity Type", "Customer ID",
            SUM("Credit Amount") AS "Credit", SUM("Debit Amount") AS "Debit"
            FROM "Accrual Transactions (Zoho Books)"
            WHERE "Account ID" = '{account_id}'
            GROUP BY "Entity ID", "Entity Type", "Customer ID"''',
    }
    data = {key: analytics.queries.execute(workspace_id=workspace_id, sql_query=sql,
            max_attempts=30, poll_interval=2.0) for key, sql in queries.items()}
    if len(data["account"]) != 1 or to_text(data["account"][0].get("Account ID")) != account_id:
        raise ReconciliationError("Analytics account identity is missing or ambiguous")

    def amount(row: dict[str, Any], field: str) -> Decimal:
        raw = row.get(field)
        if isinstance(raw, str):
            raw = re.sub(r"^[A-Z]{3}\s+", "", raw.strip())
        value = to_finite_decimal(raw, allow_commas=True)
        if value is None:
            raise ReconciliationError(f"Invalid Analytics {field}: {row!r}")
        return value

    ledger_balance = Decimal(0)
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in data["postings"]:
        row["net_credit_bcy"] = amount(row, "Credit") - amount(row, "Debit")
        ledger_balance += row["net_credit_bcy"]
        by_entity.setdefault(to_text(row.get("Entity ID")), []).append(row)
    seen = set()
    total = Decimal(0)
    customers: dict[str, dict[str, Any]] = {}
    for row in data["payments"]:
        identifier = to_text(row.get("Payment ID"))
        customer_id = to_text(row.get("Customer ID"))
        if not identifier or identifier in seen or not customer_id:
            raise ReconciliationError("Missing or duplicate Analytics payment/customer identity")
        seen.add(identifier)
        unused = amount(row, "Unused Amount (BCY)")
        if unused <= 0 or unused > amount(row, "Amount (BCY)"):
            raise ReconciliationError(f"Invalid unused balance for payment {identifier}")
        row["account_entity_matches"] = by_entity.get(identifier, [])
        total += unused
        customer = customers.setdefault(customer_id, {"customer_id": customer_id,
            "customer_name": row.get("Customer Name"), "unused_bcy": Decimal(0), "payment_count": 0})
        customer["unused_bcy"] += unused
        customer["payment_count"] += 1
    return {"account": data["account"][0], "unused_payment_total_bcy": total,
        "account_net_credit_bcy": ledger_balance,
        "ledger_less_unused_bcy": ledger_balance - total,
        "payments": data["payments"], "account_posting_groups": data["postings"],
        "customers": sorted(customers.values(), key=lambda row: row["unused_bcy"], reverse=True),
        "limitations": ["Analytics source data may lag Books; no connector refresh was requested.",
            "Account balance is the sum of available accrual credits less debits; source opening balances and completeness need verification.",
            "Entity ID matches are evidence only. Unused payments without matches remain candidates, not confirmed account associations.",
            "A ledger difference may include journals, opening balances, refunds, or synchronization timing."]}
