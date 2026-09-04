"""Human review queue for the live Creator ``Online_Payments`` report."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.exceptions import ReconciliationError
from ..core.matching import (
    get_bank_reference,
    parse_date,
    to_decimal as _decimal,
    to_text as _text,
)
from .allocator import (
    CLOSED_INVOICE_STATUSES as _CLOSED_INVOICE_STATUSES,
    allocate_invoices_oldest_due_first,
    fetch_open_invoices,
)
from .cheques import attach_presented_dates, normalize_cheque_number
from .types import InvoiceAllocation, PaymentProposal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(payload: Any, keys: Sequence[str]) -> Optional[str]:
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                return str(value)
        for value in payload.values():
            found = _identifier(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _identifier(value, keys)
            if found:
                return found
    return None


def _identifiers(payload: Any, keys: Sequence[str]) -> set[str]:
    """Return every scalar identifier stored under any of ``keys``."""
    found: set[str] = set()
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                found.add(str(value))
        for value in payload.values():
            found.update(_identifiers(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            found.update(_identifiers(value, keys))
    return found


def _cheque_reference_suffixes(value: Any) -> set[str]:
    """Return the final four digits of each cheque-like number in ``value``.

    Bank narrations commonly include the cheque number alongside clearing dates
    and other identifiers, so each numeric run is considered independently.
    """
    return {
        digits[-4:]
        for digits in re.findall(r"\d+", _text(value))
        if len(digits) >= 4
    }


@dataclass(frozen=True)
class OnlinePaymentReviewConfig:
    creator_app_link_name: str
    bank_account_id: str = ""
    bank_accounts: Tuple[Tuple[str, str], ...] = ()
    payment_report_link_name: str = "Online_Payments"
    payment_reports: Tuple[Tuple[str, str], ...] = ()
    cheque_detail_report_link_name: str = "All_Cheque_Details"
    customer_report_link_name: str = "All_Customers1"
    creator_checkpoint_report_link_name: str = "All_Payments"
    creator_books_id_field: str = "Books_Transaction_Id"
    creator_payment_number_field: str = "PaymentNo"
    date_tolerance_days: int = 0
    cheque_date_tolerance_days: int = 7
    amount_tolerance: Decimal = Decimal("0")
    state_path: Path = Path(
        "output/collection_reconciliation/online_payments_review.json"
    )

    def configured_banks(self) -> Tuple[Tuple[str, str], ...]:
        if self.bank_accounts:
            return tuple(
                (str(name).strip(), str(account_id).strip())
                for name, account_id in self.bank_accounts
                if str(name).strip() and str(account_id).strip()
            )
        if self.bank_account_id:
            return (("Bank", str(self.bank_account_id)),)
        raise ValueError("At least one bank account is required.")

    def configured_reports(self) -> Tuple[Tuple[str, str], ...]:
        if self.payment_reports:
            return tuple(
                (str(payment_type).strip(), str(report_name).strip())
                for payment_type, report_name in self.payment_reports
                if str(payment_type).strip() and str(report_name).strip()
            )
        return (("Online", self.payment_report_link_name),)


class OnlinePaymentReviewService:
    """Build and mutate a persistent, explicitly approved payment review queue."""

    def __init__(self, creator_client: Any, books_client: Any, config: OnlinePaymentReviewConfig):
        self.creator = creator_client
        self.books = books_client
        self.config = config
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.config.state_path.exists():
                return self._empty_batch()
            return json.loads(self.config.state_path.read_text(encoding="utf-8"))

    def refresh(self) -> Dict[str, Any]:
        """Read live Creator/Books data and rebuild proposals without writing to Zoho."""
        with self._lock:
            previous = self.load()
            previous_entries = {
                str(entry.get("id")): entry for entry in previous.get("entries", [])
            }
            payments = self._all_creator_payments()
            customers = self.creator.get_all_records(
                self.config.creator_app_link_name,
                self.config.customer_report_link_name,
            )
            customer_ids = {
                _text(row.get("ID")): _text(row.get("Customer_Id"))
                for row in customers
                if _text(row.get("ID"))
            }
            bank_transactions = self._all_uncategorized_bank_transactions()

            used_transaction_ids = set()
            invoice_cache: Dict[str, List[Mapping[str, Any]]] = {}
            entries = []
            for payment in payments:
                entry = self._proposal(payment, customer_ids, bank_transactions, used_transaction_ids)
                old = previous_entries.get(entry["id"])
                if old and old.get("push_status") == "pushed":
                    terminal = dict(old)
                    terminal["archived"] = False
                    self._migrate_bank_identity(terminal, previous)
                    entries.append(terminal)
                    continue
                self._attach_invoice_preview(entry, invoice_cache)
                if old and old.get("fingerprint") == entry["fingerprint"]:
                    for key in (
                        "decision",
                        "push_status",
                        "retry_stage",
                        "books_payment_id",
                        "books_payment_number",
                        "decision_at",
                        "pushed_at",
                        "error",
                    ):
                        if key in old:
                            entry[key] = old[key]
                entries.append(entry)

            current_ids = {entry["id"] for entry in entries}
            for old in previous.get("entries", []):
                if (
                    _text(old.get("id")) not in current_ids
                    and old.get("push_status") == "pushed"
                ):
                    archived = dict(old)
                    archived["archived"] = True
                    self._migrate_bank_identity(archived, previous)
                    entries.append(archived)

            batch = {
                "version": 2,
                "reports": [
                    {"payment_type": payment_type, "report": report_name}
                    for payment_type, report_name in self.config.configured_reports()
                ],
                "bank_accounts": [
                    {"name": name, "account_id": account_id}
                    for name, account_id in self.config.configured_banks()
                ],
                "refreshed_at": _now(),
                "entries": entries,
            }
            self._save(batch)
            return batch

    def reject(self, entry_id: str) -> Dict[str, Any]:
        with self._lock:
            batch, entry = self._entry(entry_id)
            if entry.get("push_status") == "pushed" or entry.get("books_payment_id"):
                raise ReconciliationError(
                    "An entry with a Books payment checkpoint cannot be rejected."
                )
            entry.update(
                {
                    "decision": "rejected",
                    "decision_at": _now(),
                    "error": "",
                }
            )
            self._save(batch)
            return entry

    def accept_and_push(
        self,
        entry_id: str,
        current_bank_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Push one approved proposal to Books, then checkpoint it in Creator."""
        with self._lock:
            batch, entry = self._entry(entry_id)
            if not entry.get("bank"):
                raise ReconciliationError("This entry has no unique bank match to accept.")
            if not entry.get("reviewable"):
                raise ReconciliationError(
                    entry.get("allocation_error")
                    or "This entry has no invoice allocation to accept."
                )
            if entry.get("push_status") == "pushed":
                return entry

            entry.update(
                {
                    "decision": "accepted",
                    "decision_at": entry.get("decision_at") or _now(),
                    "error": "",
                }
            )
            self._save(batch)

            try:
                self._push_entry(batch, entry, current_bank_by_id=current_bank_by_id)
            except Exception as exc:
                stage = _text(entry.get("push_status"))
                if stage in {
                    "payment_created",
                    "match_requested",
                    "bank_matched",
                    "creator_updated",
                }:
                    entry["retry_stage"] = stage
                entry["push_status"] = "failed"
                entry["error"] = str(exc)
                self._save(batch)
                raise
            return entry

    def accept_many(self, entry_ids: Sequence[str]) -> Dict[str, Any]:
        """Push selected entries sequentially using one current bank snapshot."""
        selected = list(dict.fromkeys(_text(entry_id) for entry_id in entry_ids if _text(entry_id)))
        if not selected:
            raise ReconciliationError("Select at least one payment to accept.")
        if len(selected) > 200:
            raise ReconciliationError("At most 200 payments can be accepted at once.")

        current_rows = self._all_uncategorized_bank_transactions()
        current_bank_by_id = {
            _text(row.get("transaction_id") or row.get("id")): row
            for row in current_rows
            if _text(row.get("transaction_id") or row.get("id"))
        }
        pushed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for entry_id in selected:
            try:
                entry = self.accept_and_push(
                    entry_id,
                    current_bank_by_id=current_bank_by_id,
                )
                pushed.append(
                    {
                        "id": entry_id,
                        "books_payment_id": entry.get("books_payment_id", ""),
                        "push_status": entry.get("push_status", ""),
                    }
                )
            except Exception as exc:
                failed.append({"id": entry_id, "error": str(exc)})
        return {
            "selected": len(selected),
            "pushed": pushed,
            "failed": failed,
        }

    def _push_entry(
        self,
        batch: Dict[str, Any],
        entry: Dict[str, Any],
        current_bank_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> None:
        stage = _text(
            entry.get("retry_stage")
            if entry.get("push_status") == "failed"
            else entry.get("push_status")
        )
        bank_id = _text(entry["bank"].get("transaction_id"))
        bank_account_id = _text(entry.get("bank_account_id"))
        if not bank_id:
            raise ReconciliationError("The proposed bank transaction has no ID.")
        if not bank_account_id:
            raise ReconciliationError("The proposed bank transaction has no bank account ID.")
        if not _text(entry["creator"].get("books_customer_id")):
            raise ReconciliationError("The Creator customer has no Zoho Books Customer_Id.")

        if stage not in ("bank_matched", "creator_updated"):
            if current_bank_by_id is None:
                current = self._current_bank_transaction(bank_id, bank_account_id)
            else:
                current = current_bank_by_id.get(bank_id)
                if not current:
                    raise ReconciliationError(
                        "The proposed bank transaction is no longer uncategorized. Refresh the queue."
                    )
            self._require_same_match(entry, current)

        books_payment_id = _text(entry.get("books_payment_id"))
        books_payment_number = _text(entry.get("books_payment_number"))
        if not books_payment_id:
            allocations, unallocated = self._invoice_allocations(
                entry["creator"]["books_customer_id"],
                entry["creator"]["amount"],
            )
            if not allocations:
                raise ReconciliationError(
                    "No open customer invoices are available. Payment creation was blocked "
                    "to prevent the full amount becoming unused credit."
                )
            entry.update(
                {
                    "invoice_allocations": allocations,
                    "unallocated_amount": float(unallocated),
                    "allocation_status": (
                        "fully_allocated" if unallocated == 0 else "partially_allocated"
                    ),
                    "allocation_error": "",
                    "allocation_refreshed_at": _now(),
                }
            )
            self._save(batch)
            response = self.books.customer_payments.create(
                self._customer_payment_payload(entry, allocations)
            )
            books_payment_id = _identifier(
                response,
                ("payment_id", "customer_payment_id", "transaction_id"),
            ) or ""
            if not books_payment_id:
                raise ReconciliationError(
                    "Books created a customer payment but returned no payment ID."
                )
            books_payment_number = _identifier(response, ("payment_number",)) or ""
            entry.update(
                {
                    "books_payment_id": books_payment_id,
                    "books_payment_number": books_payment_number,
                    "push_status": "payment_created",
                }
            )
            entry.pop("retry_stage", None)
            stage = "payment_created"
            self._save(batch)

        if not books_payment_number:
            payment_response = self.books.customer_payments.get(books_payment_id)
            books_payment_number = _identifier(
                payment_response,
                ("payment_number",),
            ) or ""
            if not books_payment_number:
                raise ReconciliationError(
                    "Books returned no payment number for the created customer payment. "
                    "The existing payment will be reused on retry."
                )
            entry["books_payment_number"] = books_payment_number
            self._save(batch)

        if stage not in ("bank_matched", "creator_updated"):
            matches = self.books.bank_transactions.get_matches(bank_id)
            rows = matches.get("matching_transactions", []) if isinstance(matches, dict) else []
            candidate = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and _text(row.get("transaction_id")) == books_payment_id
                ),
                None,
            )
            if not candidate:
                # Books can expose the invoice-application ID rather than the
                # parent payment ID for a single-invoice customer payment.
                payment_response = self.books.customer_payments.get(books_payment_id)
                application_ids = _identifiers(
                    payment_response,
                    ("invoice_payment_id",),
                )
                candidate = next(
                    (
                        row
                        for row in rows
                        if isinstance(row, dict)
                        and _text(row.get("transaction_id")) in application_ids
                    ),
                    None,
                )
            if not candidate:
                raise ReconciliationError(
                    "The created Books customer payment is not a bank match candidate."
                )
            match_transaction_id = _text(candidate.get("transaction_id"))
            transaction_type = _text(candidate.get("transaction_type"))
            if not transaction_type:
                raise ReconciliationError("The Books match candidate has no transaction_type.")
            entry["push_status"] = "match_requested"
            self._save(batch)
            self.books.bank_transactions.match(
                bank_id,
                [
                    {
                        "transaction_id": match_transaction_id,
                        "transaction_type": transaction_type,
                    }
                ],
            )
            entry["push_status"] = "bank_matched"
            entry.pop("retry_stage", None)
            stage = "bank_matched"
            self._save(batch)

        if stage != "creator_updated":
            self._checkpoint_creator(
                entry,
                books_payment_id,
                books_payment_number,
            )
            entry["push_status"] = "creator_updated"
            entry.pop("retry_stage", None)
            self._save(batch)

        entry.update({"push_status": "pushed", "pushed_at": _now(), "error": ""})
        entry.pop("retry_stage", None)
        self._save(batch)

    def _checkpoint_creator(
        self,
        entry: Mapping[str, Any],
        books_payment_id: str,
        books_payment_number: str,
    ) -> None:
        """Write and verify the Books payment checkpoint in Creator."""
        record_id = _text(entry.get("id"))
        report_name = self.config.creator_checkpoint_report_link_name
        response = self.creator.update_records(
            self.config.creator_app_link_name,
            report_name,
            {
                "data": {
                    self.config.creator_books_id_field: books_payment_id,
                    self.config.creator_payment_number_field: books_payment_number,
                }
            },
            record_id=record_id,
        )
        self._require_creator_update_success(response)

        readback = self.creator.get_records(
            self.config.creator_app_link_name,
            report_name,
            params={
                "criteria": f"ID == {record_id}",
                "field_config": "all",
            },
        )
        rows = readback.get("data", []) if isinstance(readback, Mapping) else []
        record = next(
            (
                row
                for row in rows
                if isinstance(row, Mapping) and _text(row.get("ID")) == record_id
            ),
            None,
        )
        actual = _text(record.get(self.config.creator_books_id_field)) if record else ""
        actual_number = (
            _text(record.get(self.config.creator_payment_number_field)) if record else ""
        )
        if actual != books_payment_id or actual_number != books_payment_number:
            raise ReconciliationError(
                "Creator checkpoint verification failed: Books_Transaction_Id and Payment# "
                "were not both saved. The existing Books payment will be reused on retry."
            )

    @staticmethod
    def _require_creator_update_success(response: Any) -> None:
        if not isinstance(response, Mapping):
            raise ReconciliationError("Creator returned an invalid update response.")
        payloads: List[Mapping[str, Any]] = [response]
        data = response.get("data")
        if isinstance(data, Mapping):
            payloads.append(data)
        elif isinstance(data, list):
            payloads.extend(row for row in data if isinstance(row, Mapping))
        for payload in payloads:
            code = payload.get("code")
            if code is not None and _text(code) not in {"0", "3000"}:
                message = _text(payload.get("message") or payload.get("description"))
                raise ReconciliationError(
                    f"Creator rejected the checkpoint update (code={code})"
                    + (f": {message}" if message else ".")
                )

    def _proposal(
        self,
        payment: Mapping[str, Any],
        customer_ids: Mapping[str, str],
        bank_transactions: Sequence[Mapping[str, Any]],
        used_transaction_ids: set,
    ) -> Dict[str, Any]:
        creator_id = _text(payment.get("ID"))
        lookup = payment.get("Customer_Name") if isinstance(payment.get("Customer_Name"), dict) else {}
        creator_customer_id = _text(lookup.get("ID"))
        normalized = {
            "date": _text(
                payment.get("_review_presented_date")
                if _text(payment.get("_review_payment_type")).casefold() == "cheque"
                else payment.get("Payment_Date")
            ),
            "amount": _text(payment.get("Payment_Amount")),
            "reference": _text(payment.get("Reference")),
            "payment_id": _text(payment.get("Payment_ID")),
            "customer_name": _text(lookup.get("zc_display_value") or lookup.get("Name")),
            "creator_customer_id": creator_customer_id,
            "books_customer_id": customer_ids.get(creator_customer_id, ""),
            "payment_type": _text(payment.get("_review_payment_type")) or "Online",
            "date_tolerance_days": (
                self.config.cheque_date_tolerance_days
                if _text(payment.get("_review_payment_type")).casefold() == "cheque"
                else self.config.date_tolerance_days
            ),
        }
        date_error = _text(payment.get("_review_presented_date_error"))
        if date_error:
            candidate, reason = None, date_error
        else:
            candidate, reason = self._find_transaction(
                normalized, bank_transactions, used_transaction_ids
            )
        bank = self._display_bank(candidate) if candidate else None
        if bank:
            used_transaction_ids.add(bank["transaction_id"])
        fingerprint_payload = {
            "creator": normalized,
            "bank_transaction_id": bank.get("transaction_id") if bank else None,
            "reason": reason,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "id": creator_id,
            "fingerprint": fingerprint,
            "creator": normalized,
            "payment_type": _text(payment.get("_review_payment_type")) or "Online",
            "source_report": _text(payment.get("_review_report_link_name"))
            or self.config.payment_report_link_name,
            "bank": bank,
            "bank_name": _text((candidate or {}).get("_review_bank_name")),
            "bank_account_id": _text(
                (candidate or {}).get("_review_bank_account_id")
            ),
            "reason": reason,
            "reviewable": bool(bank and normalized["books_customer_id"]),
            "decision": "pending",
            "push_status": "not_started",
            "books_payment_id": "",
            "books_payment_number": "",
            "error": "",
        }

    def _find_transaction(
        self,
        payment: Mapping[str, Any],
        transactions: Sequence[Mapping[str, Any]],
        used_transaction_ids: set,
    ) -> Tuple[Optional[Mapping[str, Any]], str]:
        payment_date = parse_date(payment.get("date"))
        amount = _decimal(payment.get("amount"))
        reference = _text(payment.get("reference")).casefold()
        if not payment_date or amount is None:
            return None, "Invalid payment date or amount"
        if not reference:
            return None, "Missing reference number"

        candidates = []
        for transaction in transactions:
            transaction_id = _text(transaction.get("transaction_id") or transaction.get("id"))
            if not transaction_id or transaction_id in used_transaction_ids:
                continue
            transaction_date = parse_date(
                transaction.get("date") or transaction.get("transaction_date")
            )
            transaction_amount = _decimal(transaction.get("amount"))
            if not transaction_date or transaction_amount is None:
                continue
            date_tolerance_days = int(
                payment.get("date_tolerance_days", self.config.date_tolerance_days)
            )
            if abs((transaction_date - payment_date).days) > date_tolerance_days:
                continue
            if abs(abs(transaction_amount) - abs(amount)) > Decimal(str(self.config.amount_tolerance)):
                continue
            account_id = _text(transaction.get("_review_bank_account_id"))
            bank_reference = _text(
                get_bank_reference(transaction, account_id)
            ).casefold()
            narration = _text(
                transaction.get("description") or transaction.get("narration")
            ).casefold()
            if _text(payment.get("payment_type")).casefold() == "cheque":
                cheque_suffixes = _cheque_reference_suffixes(reference)
                bank_suffixes = (
                    _cheque_reference_suffixes(bank_reference)
                    | _cheque_reference_suffixes(narration)
                )
                matched = bool(cheque_suffixes & bank_suffixes)
            else:
                matched = reference == bank_reference or reference in narration
            if matched:
                candidates.append(transaction)

        if len(candidates) == 1:
            return candidates[0], "Unique date, amount, and reference match"
        if len(candidates) > 1:
            return None, "Multiple bank transactions match"
        return None, "No bank transaction matched"

    def _current_bank_transaction(
        self, bank_id: str, bank_account_id: str
    ) -> Mapping[str, Any]:
        rows = self.books.bank_transactions.list_all(
            params={
                "account_id": bank_account_id,
                "filter_by": "Status.Uncategorized",
            }
        )
        current = next(
            (
                row
                for row in rows
                if _text(row.get("transaction_id") or row.get("id")) == bank_id
            ),
            None,
        )
        if not current:
            raise ReconciliationError(
                "The proposed bank transaction is no longer uncategorized. Refresh the queue."
            )
        annotated = dict(current)
        annotated["_review_bank_account_id"] = bank_account_id
        annotated["_review_bank_name"] = next(
            (
                name
                for name, account_id in self.config.configured_banks()
                if account_id == bank_account_id
            ),
            "Bank",
        )
        return annotated

    def _require_same_match(self, entry: Mapping[str, Any], transaction: Mapping[str, Any]) -> None:
        current, reason = self._find_transaction(entry["creator"], [transaction], set())
        current_id = _text((current or {}).get("transaction_id") or (current or {}).get("id"))
        if current_id != _text(entry["bank"].get("transaction_id")):
            raise ReconciliationError(
                f"The live bank transaction no longer matches this payment: {reason}."
            )

    def _customer_payment_payload(
        self,
        entry: Mapping[str, Any],
        allocations: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        creator = entry["creator"]
        payment_date = parse_date(creator.get("date"))
        amount = _decimal(creator.get("amount"))
        if not payment_date or amount is None:
            raise ReconciliationError("A valid payment date and amount are required.")
        custom_fields = [{"label": "Creator Record ID", "value": entry["id"]}]
        if creator.get("payment_id"):
            custom_fields.append(
                {"label": "Creator Payment ID", "value": creator["payment_id"]}
            )
        return {
            "customer_id": creator["books_customer_id"],
            "payment_mode": (
                "check" if _text(entry.get("payment_type")).casefold() == "cheque"
                else "banktransfer"
            ),
            "date": payment_date.isoformat(),
            "amount": float(abs(amount)),
            "reference_number": creator["reference"],
            "description": entry["bank"].get("description") or "Creator reconciliation",
            "account_id": entry["bank_account_id"],
            "invoices": [
                {
                    "invoice_id": allocation["invoice_id"],
                    "amount_applied": allocation["amount_applied"],
                }
                for allocation in allocations
            ],
            "custom_fields": custom_fields,
        }

    def _open_invoices(self, books_customer_id: str) -> List[Mapping[str, Any]]:
        return fetch_open_invoices(self.books, books_customer_id)

    def _invoice_allocations(
        self,
        books_customer_id: str,
        payment_amount: Any,
        invoices: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Decimal]:
        open_invoices = list(invoices) if invoices is not None else self._open_invoices(books_customer_id)
        return allocate_invoices_oldest_due_first(payment_amount, open_invoices)

    def _attach_invoice_preview(
        self,
        entry: Dict[str, Any],
        invoice_cache: Dict[str, List[Mapping[str, Any]]],
    ) -> None:
        customer_id = _text(entry.get("creator", {}).get("books_customer_id"))
        if not entry.get("bank") or not customer_id:
            entry.update(
                {
                    "invoice_allocations": [],
                    "unallocated_amount": float(
                        abs(_decimal(entry.get("creator", {}).get("amount")) or Decimal("0"))
                    ),
                    "allocation_status": "unavailable",
                    "allocation_error": (
                        "Creator customer has no Zoho Books Customer_Id."
                        if entry.get("bank") and not customer_id
                        else ""
                    ),
                }
            )
            entry["reviewable"] = False
            return
        try:
            if customer_id not in invoice_cache:
                invoice_cache[customer_id] = self._open_invoices(customer_id)
            allocations, unallocated = self._invoice_allocations(
                customer_id,
                entry["creator"]["amount"],
                invoice_cache[customer_id],
            )
        except Exception as exc:
            entry.update(
                {
                    "invoice_allocations": [],
                    "unallocated_amount": 0,
                    "allocation_status": "unavailable",
                    "allocation_error": f"Could not load open invoices: {exc}",
                    "reviewable": False,
                }
            )
            return
        entry.update(
            {
                "invoice_allocations": allocations,
                "unallocated_amount": float(unallocated),
                "allocation_status": (
                    "fully_allocated"
                    if unallocated == 0
                    else "partially_allocated"
                    if allocations
                    else "no_open_invoices"
                ),
                "allocation_error": (
                    "No open customer invoices are available; push is blocked to prevent "
                    "unused credit."
                    if not allocations
                    else ""
                ),
                "reviewable": bool(allocations),
            }
        )

    def _display_bank(self, transaction: Mapping[str, Any]) -> Dict[str, Any]:
        account_id = _text(transaction.get("_review_bank_account_id"))
        return {
            "transaction_id": _text(transaction.get("transaction_id") or transaction.get("id")),
            "date": _text(transaction.get("date") or transaction.get("transaction_date")),
            "amount": _text(transaction.get("amount")),
            "reference": _text(
                get_bank_reference(transaction, account_id)
            ),
            "description": _text(
                transaction.get("description") or transaction.get("narration")
            ),
        }

    def _entry(self, entry_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        batch = self.load()
        entry = next(
            (row for row in batch.get("entries", []) if _text(row.get("id")) == _text(entry_id)),
            None,
        )
        if not entry:
            raise ReconciliationError(f"Review entry {entry_id} was not found.")
        return batch, entry

    def _empty_batch(self) -> Dict[str, Any]:
        return {
            "version": 2,
            "reports": [
                {"payment_type": payment_type, "report": report_name}
                for payment_type, report_name in self.config.configured_reports()
            ],
            "bank_accounts": [
                {"name": name, "account_id": account_id}
                for name, account_id in self.config.configured_banks()
            ],
            "refreshed_at": None,
            "entries": [],
        }

    def _all_creator_payments(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        has_cheques = False
        for payment_type, report_name in self.config.configured_reports():
            payments = self.creator.get_all_records(
                self.config.creator_app_link_name,
                report_name,
            )
            for payment in payments:
                annotated = dict(payment)
                annotated["_review_payment_type"] = payment_type
                annotated["_review_report_link_name"] = report_name
                rows.append(annotated)
            has_cheques = has_cheques or payment_type.casefold() == "cheque"
        if has_cheques:
            cheque_details = self.creator.get_all_records(
                self.config.creator_app_link_name,
                self.config.cheque_detail_report_link_name,
            )
            self._attach_presented_dates(rows, cheque_details)
        return rows

    @staticmethod
    def _cheque_number(value: Any) -> str:
        return normalize_cheque_number(value)

    def _attach_presented_dates(
        self,
        payments: Sequence[Dict[str, Any]],
        cheque_details: Sequence[Mapping[str, Any]],
    ) -> None:
        attach_presented_dates(payments, cheque_details)

    def _all_uncategorized_bank_transactions(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for bank_name, account_id in self.config.configured_banks():
            transactions = self.books.bank_transactions.list_all(
                params={
                    "account_id": account_id,
                    "filter_by": "Status.Uncategorized",
                }
            )
            for transaction in transactions:
                annotated = dict(transaction)
                annotated["_review_bank_name"] = bank_name
                annotated["_review_bank_account_id"] = account_id
                rows.append(annotated)
        return rows

    def _migrate_bank_identity(
        self, entry: Dict[str, Any], previous_batch: Mapping[str, Any]
    ) -> None:
        entry.setdefault("payment_type", "Online")
        entry.setdefault("source_report", self.config.payment_report_link_name)
        if entry.get("bank_account_id"):
            return
        previous_account_id = _text(previous_batch.get("bank_account_id"))
        if not previous_account_id:
            return
        name = next(
            (
                bank_name
                for bank_name, account_id in self.config.configured_banks()
                if account_id == previous_account_id
            ),
            "Bank",
        )
        entry["bank_account_id"] = previous_account_id
        entry["bank_name"] = name

    def _save(self, batch: Mapping[str, Any]) -> None:
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(batch, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
