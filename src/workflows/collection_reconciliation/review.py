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
from .identifiers import identifier as _identifier, identifiers as _identifiers
from .payments import customer_payment_payload
from .allocator import (
    CLOSED_INVOICE_STATUSES as _CLOSED_INVOICE_STATUSES,
    allocate_invoices_oldest_due_first,
    fetch_open_invoices,
)
from .cheques import attach_presented_dates, normalize_cheque_number
from .bank_statement import (
    CustomerFinderIndex,
    bank_line_kind,
    extract_remitter_tokens,
    is_travel_allowance_withdrawal,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    analytics_workspace_id: str = ""
    customer_finder_view_id: str = ""
    travel_expense_account_name: str = "Employee Travel Expense"
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

    def __init__(self, creator_client: Any, books_client: Any, config: OnlinePaymentReviewConfig, analytics_client: Any = None):
        self.creator = creator_client
        self.books = books_client
        self.analytics = analytics_client
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
            raw_entries = []
            for payment in payments:
                entry = self._proposal(payment, customer_ids, bank_transactions, used_transaction_ids)
                raw_entries.append(entry)

            # Collect remitter tokens for targeted historical lookup
            all_tokens: set[str] = set()
            for entry in raw_entries:
                bank = entry.get("bank")
                if bank:
                    all_tokens.update(extract_remitter_tokens(bank.get("description")))
                for cand in entry.get("ambiguous_candidates", []):
                    all_tokens.update(extract_remitter_tokens(cand.get("description")))
                for cand in entry.get("possible_candidates", []):
                    all_tokens.update(extract_remitter_tokens(cand.get("description")))
            for tx in bank_transactions:
                if not is_travel_allowance_withdrawal(tx):
                    all_tokens.update(extract_remitter_tokens(tx.get("description")))

            customer_finder_rows = self._query_historical_customer_finder(sorted(all_tokens))
            customer_finder = CustomerFinderIndex(customer_finder_rows)

            invoice_cache: Dict[str, List[Mapping[str, Any]]] = {}
            entries = []
            for entry in raw_entries:
                for candidate in entry["ambiguous_candidates"]:
                    cand_tokens = extract_remitter_tokens(candidate.get("description"))
                    candidate["suggested_customer_names"] = (
                        self._suggest_names_for_tokens(cand_tokens, customer_finder_rows)
                        or customer_finder.suggest(candidate)
                    )
                self._check_customer_name(entry, customer_finder_rows)
                old = previous_entries.get(entry["id"])
                if old and old.get("push_status") == "pushed":
                    terminal = dict(old)
                    terminal["archived"] = False
                    self._migrate_bank_identity(terminal, previous)
                    entries.append(terminal)
                    continue
                self._attach_invoice_preview(entry, invoice_cache)
                if entry.get("customer_name_valid") is False:
                    entry["reviewable"] = False
                    entry["reason"] = entry["customer_name_reason"]
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
                    if old.get("manual_reference_override"):
                        for key in (
                            "bank",
                            "bank_name",
                            "bank_account_id",
                            "manual_reference_override",
                            "reviewable",
                            "reason",
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

            previous_bank = {
                _text(row.get("transaction_id")): row
                for row in previous.get("bank_suggestions", [])
            }
            bank_suggestions = []
            for transaction in bank_transactions:
                transaction_id = _text(transaction.get("transaction_id") or transaction.get("id"))
                if not transaction_id or transaction_id in used_transaction_ids:
                    continue
                displayed = self._display_bank(transaction)
                displayed.update({
                    "bank_name": _text(transaction.get("_review_bank_name")),
                    "bank_account_id": _text(transaction.get("_review_bank_account_id")),
                    "kind": bank_line_kind(transaction),
                    "customer_suggestions": customer_finder.suggest(transaction) if bank_line_kind(transaction) != "travel_allowance" else [],
                    "expense_account_name": self.config.travel_expense_account_name if is_travel_allowance_withdrawal(transaction) else "",
                    "categorization_status": "pending",
                })
                if previous_bank.get(transaction_id, {}).get("categorization_status") == "categorized":
                    continue
                bank_suggestions.append(displayed)

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
                "bank_suggestions": bank_suggestions,
            }
            self._save(batch)
            return batch

    def categorize_travel_expense(self, transaction_id: str) -> Dict[str, Any]:
        """Categorize one reviewed TA withdrawal after validating live Books state."""
        with self._lock:
            batch = self.load()
            proposal = next(
                (row for row in batch.get("bank_suggestions", []) if _text(row.get("transaction_id")) == transaction_id),
                None,
            )
            if not proposal or proposal.get("kind") != "travel_allowance":
                raise ReconciliationError("No travel allowance proposal exists for this bank line.")
            if proposal.get("categorization_status") == "categorized":
                return proposal
            account_id = _text(proposal.get("bank_account_id"))
            current = self._current_bank_transaction(transaction_id, account_id)
            if not is_travel_allowance_withdrawal(current):
                raise ReconciliationError("The live bank line is no longer a TA withdrawal.")
            if (
                parse_date(current.get("date") or current.get("transaction_date")) != parse_date(proposal.get("date"))
                or _decimal(current.get("amount")) != _decimal(proposal.get("amount"))
                or _text(current.get("description") or current.get("narration")) != _text(proposal.get("description"))
            ):
                raise ReconciliationError("The live bank line changed. Refresh before categorizing.")
            accounts = self.books.chart_of_accounts.list_all()
            matching_accounts = [
                row for row in accounts
                if _text(row.get("account_name")).casefold() == self.config.travel_expense_account_name.casefold()
                and _text(row.get("account_id"))
                and _text(row.get("account_type")).casefold() in {"expense", "other_expense"}
                and row.get("is_active") is not False
            ]
            if len(matching_accounts) != 1:
                raise ReconciliationError("A unique active Employee Travel Expense account was not found in Books.")
            amount = _decimal(current.get("amount"))
            if amount is None or amount == 0:
                raise ReconciliationError("The bank withdrawal has no valid amount.")
            payload = {
                "account_id": _text(matching_accounts[0]["account_id"]),
                "paid_through_account_id": account_id,
                "date": _text(current.get("date") or current.get("transaction_date")),
                "amount": float(abs(amount)),
                "description": _text(current.get("description") or current.get("narration")),
                "reference_number": _text(current.get("reference_number")),
            }
            response = self.books.bank_transactions.categorize_as_expense(transaction_id, payload)
            if not isinstance(response, Mapping) or _text(response.get("code")) != "0":
                raise ReconciliationError("Books rejected the expense categorization.")
            proposal["categorization_status"] = "categorized"
            proposal["expense_account_id"] = payload["account_id"]
            self._save(batch)
            return proposal

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
        *,
        selected_bank_transaction_id: str = "",
        allow_reference_override: bool = False,
    ) -> Dict[str, Any]:
        """Push one approved proposal to Books, then checkpoint it in Creator."""
        with self._lock:
            batch, entry = self._entry(entry_id)
            if not entry.get("bank") and selected_bank_transaction_id:
                if not allow_reference_override:
                    raise ReconciliationError(
                        "Explicit confirmation of the reference mismatch is required."
                    )
                possible = next(
                    (
                        row
                        for row in entry.get("possible_candidates", [])
                        if _text(row.get("transaction_id"))
                        == _text(selected_bank_transaction_id)
                    ),
                    None,
                )
                if not possible:
                    raise ReconciliationError(
                        "The selected bank transaction is not a possible match for this payment."
                    )
                if not _text(entry.get("creator", {}).get("books_customer_id")):
                    raise ReconciliationError(
                        "The Creator customer has no Zoho Books Customer_Id."
                    )
                entry.update(
                    {
                        "bank": {
                            key: value
                            for key, value in possible.items()
                            if key not in {"bank_name", "bank_account_id"}
                        },
                        "bank_name": _text(possible.get("bank_name")),
                        "bank_account_id": _text(possible.get("bank_account_id")),
                        "manual_reference_override": True,
                        "reviewable": True,
                        "reason": "Manually selected date-and-amount match; reference differs",
                    }
                )
                self._save(batch)
            if not entry.get("bank"):
                raise ReconciliationError("This entry has no unique bank match to accept.")
            if not entry.get("reviewable"):
                raise ReconciliationError(
                    entry.get("customer_name_reason") if entry.get("customer_name_valid") is False else
                    entry.get("allocation_error")
                    or "This entry has no invoice allocation to accept."
                )
            live_tokens = extract_remitter_tokens(entry["bank"].get("description"))
            self._check_customer_name(entry, self._query_historical_customer_finder(live_tokens))
            if entry.get("customer_name_valid") is False:
                self._save(batch)
                raise ReconciliationError(entry["customer_name_reason"])
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

    def accept_many(
        self,
        entry_ids: Sequence[str],
        selected_bank_transaction_ids: Optional[Mapping[str, str]] = None,
        *,
        allow_reference_override: bool = False,
    ) -> Dict[str, Any]:
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
        selected_bank_transaction_ids = selected_bank_transaction_ids or {}
        for entry_id in selected:
            try:
                entry = self.accept_and_push(
                    entry_id,
                    current_bank_by_id=current_bank_by_id,
                    selected_bank_transaction_id=_text(
                        selected_bank_transaction_ids.get(entry_id)
                    ),
                    allow_reference_override=allow_reference_override,
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
            if entry.get("manual_reference_override"):
                self._require_same_date_amount(entry, current)
            else:
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

    def _query_historical_customer_finder(
        self, tokens: Sequence[str]
    ) -> List[Mapping[str, Any]]:
        if not self.config.customer_finder_view_id or not tokens:
            return []
        if not self.analytics or not self.config.analytics_workspace_id:
            raise ReconciliationError("Analytics customer-name validation is not configured.")

        unique_tokens = sorted({t.strip() for t in tokens if t and len(t.strip()) >= 3})
        if not unique_tokens:
            return []

        # If queries.execute is available, run targeted SQL
        if hasattr(self.analytics, "queries") and callable(getattr(self.analytics.queries, "execute", None)):
            try:
                all_rows: List[Mapping[str, Any]] = []
                chunk_size = 35
                for i in range(0, len(unique_tokens), chunk_size):
                    chunk = unique_tokens[i:i + chunk_size]
                    clauses = []
                    for token in chunk:
                        safe = token.replace("'", "''")
                        clauses.append(f'"Description" LIKE \'%{safe}%\'')
                    where_clause = " OR ".join(clauses)
                    table_name = "Payment Customer Finder"
                    sql = (
                        f'SELECT "Customer Name", "Description" '
                        f'FROM "{table_name}" '
                        f'WHERE "Customer Name" IS NOT NULL AND "Customer Name" != \'\' '
                        f'AND ({where_clause})'
                    )
                    rows = self.analytics.queries.execute(
                        self.config.analytics_workspace_id,
                        sql,
                    )
                    if isinstance(rows, list):
                        all_rows.extend(rows)
                if all_rows or not hasattr(self.analytics, "views"):
                    return all_rows
            except Exception:
                if not hasattr(self.analytics, "views"):
                    raise

        # Fallback to views.export_all (e.g. mock views in tests or when SQL is unavailable)
        if hasattr(self.analytics, "views") and callable(getattr(self.analytics.views, "export_all", None)):
            rows = self.analytics.views.export_all(
                self.config.analytics_workspace_id,
                self.config.customer_finder_view_id,
                max_attempts=60,
            )
            if isinstance(rows, list):
                return rows

        return []

    def _customer_finder_rows(self) -> List[Mapping[str, Any]]:
        """Fallback for callers requesting all rows."""
        return self._query_historical_customer_finder(["UPI", "NEFT", "IMPS", "CHQ"])

    @staticmethod
    def _suggest_names_for_tokens(
        tokens: Sequence[str], historical_rows: Sequence[Mapping[str, Any]]
    ) -> List[str]:
        if not tokens or not historical_rows:
            return []
        tokens_lower = [t.casefold() for t in tokens if t]
        names = {
            _text(row.get("Customer Name")).strip()
            for row in historical_rows
            if isinstance(row, Mapping) and _text(row.get("Customer Name"))
            and any(t in _text(row.get("Description")).casefold() for t in tokens_lower)
        }
        return sorted((n for n in names if n), key=str.casefold)

    def _check_customer_name(
        self, entry: Dict[str, Any], historical_rows: Sequence[Mapping[str, Any]]
    ) -> None:
        """Verify Creator customer name against historical Analytics remitter records."""
        if not self.config.customer_finder_view_id or not entry.get("bank"):
            return

        bank_desc = entry["bank"].get("description")
        tokens = extract_remitter_tokens(bank_desc)
        if not tokens:
            entry["customer_name_valid"] = None
            entry["customer_name_reason"] = "No remitter identifiers in bank narration for Analytics lookup."
            entry["historical_customer_names"] = []
            return

        tokens_lower = [t.casefold() for t in tokens if t]
        matching_rows = [
            row for row in historical_rows
            if isinstance(row, Mapping) and _text(row.get("Customer Name"))
            and any(t in _text(row.get("Description")).casefold() for t in tokens_lower)
        ]

        if not matching_rows:
            entry["customer_name_valid"] = None
            entry["customer_name_reason"] = "No historical customer match found in Analytics."
            entry["historical_customer_names"] = []
            return

        historical_names = sorted(
            {
                _text(row.get("Customer Name")).strip()
                for row in matching_rows
                if _text(row.get("Customer Name")).strip()
            },
            key=str.casefold,
        )
        entry["historical_customer_names"] = historical_names

        expected = " ".join(_text(entry["creator"].get("customer_name")).split()).casefold()

        def _matches_expected(name: str) -> bool:
            clean_name = " ".join(name.split()).casefold()
            return (
                clean_name == expected
                or expected.startswith(clean_name + " ")
                or clean_name.startswith(expected + " ")
                or clean_name.split(" - ")[0] == expected.split(" - ")[0]
            )

        has_match = any(_matches_expected(n) for n in historical_names)
        if has_match:
            entry["customer_name_valid"] = True
            entry["customer_name_reason"] = "Customer name confirmed by Analytics history."
        else:
            other_names = ", ".join(historical_names)
            entry["customer_name_valid"] = False
            entry["customer_name_reason"] = (
                f"Conflict: Analytics historical records for this remitter belong to "
                f"'{other_names}', not '{entry['creator'].get('customer_name')}'."
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
            candidate, reason, candidates, possible_candidates = (
                None,
                date_error,
                [],
                [],
            )
        else:
            candidate, reason, candidates, possible_candidates = (
                self._find_transaction_details(
                    normalized,
                    bank_transactions,
                    used_transaction_ids,
                )
            )
        bank = self._display_bank(candidate) if candidate else None

        def display_candidates(
            rows: Sequence[Mapping[str, Any]],
        ) -> List[Dict[str, Any]]:
            displayed_rows = []
            for row in rows:
                displayed = self._display_bank(row)
                displayed.update(
                    {
                        "bank_name": _text(row.get("_review_bank_name")),
                        "bank_account_id": _text(
                            row.get("_review_bank_account_id")
                        ),
                    }
                )
                displayed_rows.append(displayed)
            return displayed_rows

        ambiguous_candidates = (
            display_candidates(candidates) if len(candidates) > 1 else []
        )
        displayed_possible_candidates = display_candidates(possible_candidates)
        if bank:
            used_transaction_ids.add(bank["transaction_id"])
        fingerprint_payload = {
            "creator": normalized,
            "bank_transaction_id": bank.get("transaction_id") if bank else None,
            "ambiguous_transaction_ids": [
                row["transaction_id"] for row in ambiguous_candidates
            ],
            "possible_transaction_ids": [
                row["transaction_id"] for row in displayed_possible_candidates
            ],
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
            "ambiguous_candidates": ambiguous_candidates,
            "possible_candidates": displayed_possible_candidates,
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
        candidate, reason, _, _ = self._find_transaction_details(
            payment,
            transactions,
            used_transaction_ids,
        )
        return candidate, reason

    def _find_transaction_details(
        self,
        payment: Mapping[str, Any],
        transactions: Sequence[Mapping[str, Any]],
        used_transaction_ids: set,
    ) -> Tuple[
        Optional[Mapping[str, Any]],
        str,
        List[Mapping[str, Any]],
        List[Mapping[str, Any]],
    ]:
        payment_date = parse_date(payment.get("date"))
        amount = _decimal(payment.get("amount"))
        reference = _text(payment.get("reference")).casefold()
        if not payment_date or amount is None:
            return None, "Invalid payment date or amount", [], []

        candidates = []
        date_amount_candidates = []
        for transaction in transactions:
            transaction_id = _text(
                transaction.get("transaction_id") or transaction.get("id")
            )
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
            if abs(abs(transaction_amount) - abs(amount)) > Decimal(
                str(self.config.amount_tolerance)
            ):
                continue
            date_amount_candidates.append(transaction)
            if not reference:
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

        if not reference:
            return None, "Missing reference number", [], date_amount_candidates
        if len(candidates) == 1:
            return (
                candidates[0],
                "Unique date, amount, and reference match",
                candidates,
                [],
            )
        if len(candidates) > 1:
            return None, "Multiple bank transactions match", candidates, []
        return None, "No bank transaction matched", [], date_amount_candidates

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

    def _require_same_date_amount(
        self,
        entry: Mapping[str, Any],
        transaction: Mapping[str, Any],
    ) -> None:
        """Revalidate a manually selected reference-mismatch candidate."""
        creator = entry["creator"]
        payment_date = parse_date(creator.get("date"))
        transaction_date = parse_date(
            transaction.get("date") or transaction.get("transaction_date")
        )
        payment_amount = _decimal(creator.get("amount"))
        transaction_amount = _decimal(transaction.get("amount"))
        tolerance_days = int(
            creator.get("date_tolerance_days", self.config.date_tolerance_days)
        )
        if (
            not payment_date
            or not transaction_date
            or payment_amount is None
            or transaction_amount is None
            or abs((transaction_date - payment_date).days) > tolerance_days
            or abs(abs(transaction_amount) - abs(payment_amount))
            > Decimal(str(self.config.amount_tolerance))
        ):
            raise ReconciliationError(
                "The selected bank transaction no longer matches the payment date and amount."
            )

    def _customer_payment_payload(
        self,
        entry: Mapping[str, Any],
        allocations: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        creator = entry["creator"]
        payment_date = parse_date(creator.get("date"))
        amount = _decimal(creator.get("amount"))
        return customer_payment_payload(
            customer_id=creator["books_customer_id"],
            payment_mode=(
                "check" if _text(entry.get("payment_type")).casefold() == "cheque"
                else "banktransfer"
            ),
            payment_date=payment_date,
            amount=amount,
            reference_number=creator["reference"],
            description=entry["bank"].get("description") or "Creator reconciliation",
            account_id=entry["bank_account_id"],
            creator_record_id=entry["id"],
            creator_payment_id=creator.get("payment_id") or None,
            invoices=allocations,
        )

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
            "transaction_number": _text(transaction.get("transaction_number") or transaction.get("transaction_no")),
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
