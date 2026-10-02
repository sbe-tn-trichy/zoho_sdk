"""Read-only customer invoice discounts and payment allocation verification."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, TypedDict
import time

from .core.exceptions import ReconciliationError
from .core.matching import parse_date, to_finite_decimal, to_text


class InvoicePaymentRow(TypedDict):
    date: str
    invoice_number: str
    invoice_value: Decimal
    cd_applied: Decimal
    payment: Decimal


class PaymentAllocationRow(TypedDict):
    date: str
    payment_number: str
    invoice_number: str
    payment_amount: Decimal
    amount_applied: Decimal
    unused_amount: Decimal


@dataclass
class CustomerInvoicePaymentReview:
    customer_id: str
    customer_name: str
    invoices: list[InvoicePaymentRow]
    allocations: list[PaymentAllocationRow]
    issues: list[str]


def _amount(value: Any, label: str) -> Decimal:
    number = to_finite_decimal(value, allow_commas=True)
    if number is None or number < 0:
        raise ReconciliationError(f"Invalid {label}: {value!r}")
    return number


def invoice_discount_percentage(invoice: Mapping[str, Any]) -> Decimal:
    """Return native invoice percent, or effective percent for a flat discount."""
    discount = to_text(invoice.get("discount"))
    if discount.endswith("%"):
        percent = _amount(discount[:-1], "discount percentage")
    else:
        native = invoice.get("discount_percent")
        percent = _amount(native, "discount percentage") if native not in (None, "") else Decimal(0)
        if not percent:
            total = _amount(invoice.get("discount_total") or invoice.get("discount_amount") or 0, "discount total")
            if not total and discount:
                total = _amount(discount, "flat discount")
            if not total:
                return Decimal(0)
            base = invoice.get("discount_applied_on_amount")
            if base in (None, "", 0, "0"):
                lines = invoice.get("line_items") or []
                base = sum((_amount(row["rate"], "rate") * _amount(row["quantity"], "quantity") for row in lines), Decimal(0))
            denominator = _amount(base, "discount base")
            if not denominator:
                raise ReconciliationError("Nonzero discount has no discount base.")
            percent = total * 100 / denominator
    if percent > 100:
        raise ReconciliationError("Invoice discount percentage exceeds 100.")
    return percent.quantize(Decimal("0.01"))


def review_customer_invoices_payments(
    books: Any, customer_id: str, *, request_interval: float = 0.5
) -> CustomerInvoicePaymentReview:
    """Read all customer invoices and payment details; never mutate Books.

    Payment is the sum of payment allocations, excluding credits and write-offs.
    All invoice statuses are retained. No date range is applied.
    """
    if not customer_id.isdigit() or request_interval < 0:
        raise ValueError("A numeric customer ID and nonnegative request interval are required.")

    def detail(resource: Any, identifier: str, key: str) -> Mapping[str, Any]:
        time.sleep(request_interval)
        response = resource.get(identifier)
        record = response.get(key)
        if response.get("code") != 0 or not isinstance(record, Mapping):
            raise ReconciliationError(f"Invalid Books {key} detail for {identifier}.")
        return record

    customer = detail(books.contacts, customer_id, "contact")
    if to_text(customer.get("contact_id")) != customer_id:
        raise ReconciliationError("Books returned a different customer.")
    invoice_list = books.invoices.list_all(params={"customer_id": customer_id})
    payment_list = books.customer_payments.list_all(params={"customer_id": customer_id})
    invoices: dict[str, Mapping[str, Any]] = {}
    for row in invoice_list:
        identifier = to_text(row.get("invoice_id"))
        if not identifier or identifier in invoices:
            raise ReconciliationError("Missing or duplicate invoice ID.")
        invoice = detail(books.invoices, identifier, "invoice")
        if to_text(invoice.get("customer_id")) != customer_id or to_text(invoice.get("invoice_id")) != identifier:
            raise ReconciliationError("Invoice detail does not match the requested customer/ID.")
        invoices[identifier] = invoice

    paid = {identifier: Decimal(0) for identifier in invoices}
    allocations: list[PaymentAllocationRow] = []
    issues: list[str] = []
    seen: set[str] = set()
    for row in payment_list:
        identifier = to_text(row.get("payment_id"))
        if not identifier or identifier in seen:
            raise ReconciliationError("Missing or duplicate payment ID.")
        seen.add(identifier)
        payment = detail(books.customer_payments, identifier, "payment")
        if to_text(payment.get("customer_id")) != customer_id or to_text(payment.get("payment_id")) != identifier:
            raise ReconciliationError("Payment detail does not match the requested customer/ID.")
        total = _amount(payment.get("amount"), "payment amount")
        unused = _amount(payment.get("unused_amount", 0), "unused payment")
        applied = Decimal(0)
        for allocation in payment.get("invoices") or []:
            invoice_id = to_text(allocation.get("invoice_id"))
            amount = _amount(allocation.get("amount_applied"), "payment allocation")
            applied += amount
            if invoice_id not in paid:
                raise ReconciliationError(f"Payment {identifier} references an invoice outside the customer invoice set.")
            paid[invoice_id] += amount
            allocations.append({"date": to_text(payment.get("date")),
                "payment_number": to_text(payment.get("payment_number")),
                "invoice_number": to_text(invoices[invoice_id].get("invoice_number")),
                "payment_amount": total, "amount_applied": amount, "unused_amount": unused})
        if not payment.get("invoices"):
            allocations.append({"date": to_text(payment.get("date")),
                "payment_number": to_text(payment.get("payment_number")), "invoice_number": "",
                "payment_amount": total, "amount_applied": Decimal(0), "unused_amount": unused})
        if abs(total - applied - unused) > Decimal("0.01"):
            issues.append(f"Payment {identifier}: amount differs from allocations plus unused amount (check refunds/withholding).")

    rows: list[InvoicePaymentRow] = []
    for identifier, invoice in invoices.items():
        date = parse_date(invoice.get("date"))
        if date is None or not to_text(invoice.get("invoice_number")):
            raise ReconciliationError(f"Invoice {identifier} lacks a valid date or number.")
        rows.append({"date": date.isoformat(), "invoice_number": to_text(invoice["invoice_number"]),
            "invoice_value": _amount(invoice.get("total"), "invoice total"),
            "cd_applied": invoice_discount_percentage(invoice), "payment": paid[identifier]})
        if invoice.get("payment_made") is not None and abs(_amount(invoice["payment_made"], "invoice payment total") - paid[identifier]) > Decimal("0.01"):
            issues.append(f"Invoice {invoice['invoice_number']}: payment allocations differ from Books payment_made.")
    return CustomerInvoicePaymentReview(customer_id, to_text(customer.get("contact_name")),
        sorted(rows, key=lambda row: (row["date"], row["invoice_number"])),
        sorted(allocations, key=lambda row: (row["date"], row["payment_number"], row["invoice_number"])), issues)
