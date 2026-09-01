import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.exceptions import ReconciliationError
from ..core.matching import get_bank_reference, parse_date, to_decimal as _decimal
from .schema import (
    AUDIT_FIELD_REQUIREMENTS,
    COLLECTION_FIELD_REQUIREMENTS,
    ensure_books_customer_payment_fields,
    require_valid_schema,
    validate_creator_form_fields,
)


logger = logging.getLogger(__name__)


DEFAULT_ANALYTICS_SQL = '''SELECT
    bt."Transaction Date",
    bt."Amount",
    bt."Description" AS "Bank_Narration",
    bt."Reference Number",
    cm."Customer Name",
    cm."Customer ID",
    MATCH_SCORE(bt."Description", cm."Customer Name") AS "Match_Confidence"
FROM "Bank Transactions" bt
LEFT JOIN "Customer Master" cm
    ON LOWER(bt."Description") LIKE CONCAT('%', LOWER(cm."Customer Name"), '%')
    OR LOWER(bt."Description") LIKE CONCAT('%', LOWER(cm."Search_Keywords"), '%')
WHERE bt."Status" = 'Uncategorized'
  AND bt."Creator_Record_ID" IS NULL
  AND bt."Transaction Date" = {date}
  AND bt."Amount" = {amount}'''


@dataclass(frozen=True)
class CollectionReconciliationConfig:
    creator_app_link_name: str
    bank_account_id: str
    collection_form_link_name: str = "Collection_Records"
    collection_report_link_name: str = "Collection_Records"
    audit_form_link_name: str = "Reconciliation_Audit_Log"
    analytics_workspace_id: Optional[str] = None
    analytics_sql_template: str = DEFAULT_ANALYTICS_SQL
    date_tolerance_days: int = 0
    amount_tolerance: Decimal = Decimal("0")
    dry_run: bool = True

    def __post_init__(self) -> None:
        if not self.creator_app_link_name:
            raise ValueError("creator_app_link_name is required.")
        if not self.bank_account_id:
            raise ValueError("bank_account_id is required.")
        if self.date_tolerance_days < 0:
            raise ValueError("date_tolerance_days cannot be negative.")
        if Decimal(str(self.amount_tolerance)) < 0:
            raise ValueError("amount_tolerance cannot be negative.")


def _identifier(payload: Any, keys: Sequence[str]) -> Optional[str]:
    if isinstance(payload, dict):
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


def _record_id(record: Mapping[str, Any]) -> Optional[str]:
    return _identifier(record, ("Record_ID", "ID", "id"))


def _customer_id(record: Mapping[str, Any]) -> Optional[str]:
    direct = record.get("Customer_ID") or record.get("customer_id")
    if direct:
        return str(direct)
    lookup = record.get("Customer_Name")
    if isinstance(lookup, dict):
        return _identifier(lookup, ("ID", "id", "Customer_ID", "customer_id"))
    if lookup and str(lookup).strip().isdigit():
        return str(lookup).strip()
    return None


def _normalized_reference(value: Any) -> str:
    return str(value or "").strip().casefold()


def _books_payment_mode(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return {
        "online": "banktransfer",
        "cheque": "check",
        "cash": "cash",
    }.get(normalized, normalized or "banktransfer")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


class CollectionReconciler:
    """Reconcile Creator collection records with incoming Books bank lines."""

    def __init__(
        self,
        creator_client: Any,
        books_client: Any,
        config: CollectionReconciliationConfig,
        analytics_client: Optional[Any] = None,
    ):
        self.creator = creator_client
        self.books = books_client
        self.analytics = analytics_client
        self.config = config

    def validate_schema(
        self,
        create_missing_books_fields: bool = False,
        raise_on_error: bool = True,
    ) -> Dict[str, Any]:
        collection = validate_creator_form_fields(
            self.creator.get_fields(
                self.config.creator_app_link_name,
                self.config.collection_form_link_name,
            ),
            COLLECTION_FIELD_REQUIREMENTS,
        )
        audit = validate_creator_form_fields(
            self.creator.get_fields(
                self.config.creator_app_link_name,
                self.config.audit_form_link_name,
            ),
            AUDIT_FIELD_REQUIREMENTS,
        )
        books = ensure_books_customer_payment_fields(
            self.books,
            create_missing=create_missing_books_fields,
        )
        report = {"creator_collection": collection, "creator_audit": audit, "books": books}
        if raise_on_error:
            require_valid_schema(report)
        return report

    def run(
        self,
        create_missing_books_fields: bool = False,
    ) -> Dict[str, Any]:
        self.validate_schema(create_missing_books_fields=create_missing_books_fields)
        return self.reconcile_pending()

    def reconcile_pending(self) -> Dict[str, Any]:
        pending = self.creator.get_all_records(
            self.config.creator_app_link_name,
            self.config.collection_report_link_name,
            criteria='Reconciliation_Status == "Pending"',
        )
        transactions = self.books.bank_transactions.list_all(
            params={
                "account_id": self.config.bank_account_id,
                "filter_by": "Status.Uncategorized",
            }
        )
        confirmed: List[Dict[str, Any]] = []
        unmatched: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        used_transaction_ids = set()

        for record in pending:
            creator_id = _record_id(record)
            try:
                transaction, reason = self._find_transaction(
                    record,
                    transactions,
                    used_transaction_ids,
                )
                if transaction is None:
                    suggestions = self._analytics_suggestions(record)
                    result = {
                        "creator_record_id": creator_id,
                        "reason": reason,
                        "analytics_suggestions": suggestions,
                    }
                    unmatched.append(result)
                    self._audit(creator_id, "matching", reason, record)
                    continue

                outcome = self._reconcile_collection(record, transaction)
                transaction_id = _identifier(transaction, ("transaction_id", "id"))
                if transaction_id:
                    used_transaction_ids.add(transaction_id)
                confirmed.append(outcome)
            except Exception as exc:
                logger.exception("Collection reconciliation failed for %s", creator_id)
                result = {"creator_record_id": creator_id, "error": str(exc)}
                failed.append(result)
                self._audit(creator_id, "reconciliation", str(exc), record)

        return {
            "processed": len(pending),
            "confirmed": confirmed,
            "unmatched": unmatched,
            "failed": failed,
            "dry_run": self.config.dry_run,
        }

    def _find_transaction(
        self,
        record: Mapping[str, Any],
        transactions: Sequence[Mapping[str, Any]],
        used_transaction_ids: set,
    ) -> Tuple[Optional[Mapping[str, Any]], str]:
        payment_date = parse_date(record.get("Payment_Date"))
        amount = _decimal(record.get("Amount"))
        reference = _normalized_reference(record.get("Reference_Number"))
        if not payment_date or amount is None:
            return None, "Collection record has an invalid Payment_Date or Amount."
        if not reference:
            return None, "Collection record has no reference number; manual review is required."

        candidates: List[Mapping[str, Any]] = []
        for transaction in transactions:
            transaction_id = _identifier(transaction, ("transaction_id", "id"))
            if not transaction_id or transaction_id in used_transaction_ids:
                continue
            tx_date = parse_date(transaction.get("date") or transaction.get("transaction_date"))
            tx_amount = _decimal(transaction.get("amount"))
            if not tx_date or tx_amount is None:
                continue
            if abs((tx_date - payment_date).days) > self.config.date_tolerance_days:
                continue
            if abs(abs(tx_amount) - abs(amount)) > Decimal(str(self.config.amount_tolerance)):
                continue
            tx_reference = _normalized_reference(
                get_bank_reference(transaction, self.config.bank_account_id)
            )
            narration = _normalized_reference(
                transaction.get("description") or transaction.get("narration")
            )
            if reference == tx_reference or reference in narration:
                candidates.append(transaction)

        if len(candidates) == 1:
            return candidates[0], "exact_reference_amount_date"
        if len(candidates) > 1:
            return None, "Multiple bank transactions match date, amount, and reference."
        return None, "No bank transaction matched date, amount, and reference."

    def _reconcile_collection(
        self,
        record: Mapping[str, Any],
        transaction: Mapping[str, Any],
        source: str = "Creator_Auto",
    ) -> Dict[str, Any]:
        creator_id = _record_id(record)
        transaction_id = _identifier(transaction, ("transaction_id", "id"))
        customer_id = _customer_id(record)
        if not creator_id:
            raise ReconciliationError("Creator collection record has no Record_ID or ID.")
        if not transaction_id:
            raise ReconciliationError("Books bank transaction has no transaction ID.")
        if not customer_id:
            raise ReconciliationError("Creator Customer_Name lookup has no customer ID.")

        existing_payment_id = str(record.get("Zoho_Books_Payment_ID") or "").strip()
        if self.config.dry_run:
            payment_id = existing_payment_id or f"dry-run:{transaction_id}"
        else:
            payment_id = existing_payment_id
            if not payment_id:
                response = self.books.customer_payments.create(
                    self._customer_payment_payload(
                        record,
                        transaction,
                        customer_id,
                        creator_id,
                        source,
                    )
                )
                payment_id = _identifier(
                    response,
                    ("payment_id", "customer_payment_id", "transaction_id"),
                )
                if not payment_id:
                    raise ReconciliationError(
                        "Books created a customer payment but returned no payment ID."
                    )
                self.creator.update_records(
                    self.config.creator_app_link_name,
                    self.config.collection_report_link_name,
                    {"data": {"Zoho_Books_Payment_ID": payment_id}},
                    record_id=creator_id,
                )

            matches_response = self.books.bank_transactions.get_matches(transaction_id)
            matching_rows = (
                matches_response.get("matching_transactions", [])
                if isinstance(matches_response, dict)
                else []
            )
            existing_match = next(
                (
                    row for row in matching_rows
                    if isinstance(row, dict)
                    and str(row.get("transaction_id") or "") == payment_id
                ),
                None,
            )
            if existing_match is None:
                raise ReconciliationError(
                    "The existing Zoho_Books_Payment_ID is not a Books match candidate."
                )
            transaction_type = str(existing_match.get("transaction_type") or "").strip()
            if not transaction_type:
                raise ReconciliationError("Books match candidate has no transaction_type.")
            self.books.bank_transactions.match(
                transaction_id,
                [
                    {
                        "transaction_id": payment_id,
                        "transaction_type": transaction_type,
                    }
                ],
            )

        if not self.config.dry_run:
            try:
                self.creator.update_records(
                    self.config.creator_app_link_name,
                    self.config.collection_report_link_name,
                    {
                        "data": {
                            "Reconciliation_Status": "Confirmed",
                            "Zoho_Books_Payment_ID": payment_id,
                        }
                    },
                    record_id=creator_id,
                )
            except Exception:
                try:
                    self.books.bank_transactions.unmatch(
                        transaction_id,
                        self.config.bank_account_id,
                    )
                except Exception:
                    logger.exception(
                        "Unable to roll back Books match for transaction %s.",
                        transaction_id,
                    )
                raise
        return {
            "creator_record_id": creator_id,
            "bank_transaction_id": transaction_id,
            "books_payment_id": payment_id,
            "source": source,
        }

    def _customer_payment_payload(
        self,
        record: Mapping[str, Any],
        transaction: Mapping[str, Any],
        customer_id: str,
        creator_id: str,
        source: str,
    ) -> Dict[str, Any]:
        payment_date = parse_date(record.get("Payment_Date")) or parse_date(transaction.get("date"))
        amount = _decimal(record.get("Amount")) or _decimal(transaction.get("amount"))
        if not payment_date or amount is None:
            raise ReconciliationError("A valid payment date and amount are required.")
        custom_fields = [
            {"label": "Creator Record ID", "value": creator_id},
        ]
        creator_payment_id = record.get("Payment_ID")
        if creator_payment_id not in (None, ""):
            custom_fields.append(
                {"label": "Creator Payment ID", "value": creator_payment_id}
            )
        return {
            "customer_id": customer_id,
            "payment_mode": _books_payment_mode(record.get("Payment_Mode")),
            "date": payment_date.isoformat(),
            "amount": float(abs(amount)),
            "reference_number": str(record.get("Reference_Number") or ""),
            "description": str(transaction.get("description") or "Creator reconciliation"),
            "account_id": self.config.bank_account_id,
            "custom_fields": custom_fields,
        }

    def _analytics_suggestions(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if not self.analytics or not self.config.analytics_workspace_id:
            return []
        payment_date = parse_date(record.get("Payment_Date"))
        amount = _decimal(record.get("Amount"))
        sql = self.config.analytics_sql_template.format(
            date=_sql_literal(payment_date.isoformat() if payment_date else None),
            amount=_sql_literal(amount),
            reference_number=_sql_literal(record.get("Reference_Number")),
        )
        if hasattr(self.analytics, "queries"):
            return self.analytics.queries.execute(self.config.analytics_workspace_id, sql)
        return self.analytics.views.query_data(
            self.config.analytics_workspace_id,
            sql,
            response_format="json",
        )

    def resolve_manual(
        self,
        bank_transaction: Mapping[str, Any],
        analytics_selection: Mapping[str, Any],
        payment_mode: str = "Online",
    ) -> Dict[str, Any]:
        customer_id = _identifier(
            analytics_selection,
            ("Customer ID", "Customer_ID", "customer_id", "id"),
        )
        if not customer_id:
            raise ReconciliationError("Analytics selection has no Customer ID.")
        transaction_id = _identifier(bank_transaction, ("transaction_id", "id"))
        if not transaction_id:
            raise ReconciliationError("Bank transaction has no transaction ID.")

        creator_payload = {
            "Payment_Date": str(bank_transaction.get("date") or bank_transaction.get("transaction_date") or ""),
            "Amount": bank_transaction.get("amount"),
            "Payment_Mode": payment_mode,
            "Reference_Number": str(
                get_bank_reference(bank_transaction, self.config.bank_account_id) or ""
            ),
            "Customer_Name": customer_id,
            "Reconciliation_Status": "Pending",
        }
        if self.config.dry_run:
            record = dict(creator_payload)
            record["Customer_Name"] = {"ID": customer_id}
            record["Record_ID"] = "dry-run:creator"
            return self._reconcile_collection(record, bank_transaction, source="Manual_Analytics")

        created = self.creator.add_records(
            self.config.creator_app_link_name,
            self.config.collection_form_link_name,
            {"data": [creator_payload]},
        )
        creator_id = _identifier(created, ("Record_ID", "ID", "id"))
        if not creator_id:
            raise ReconciliationError("Creator did not return an ID for the manual collection record.")
        creator_payment_id = _identifier(created, ("Payment_ID",))
        if not creator_payment_id:
            created_rows = self.creator.get_all_records(
                self.config.creator_app_link_name,
                self.config.collection_report_link_name,
                criteria=f"ID == {creator_id}",
            )
            if created_rows:
                creator_payment_id = _identifier(created_rows[0], ("Payment_ID",))
        if not creator_payment_id:
            raise ReconciliationError(
                "Creator record has no Payment_ID for the Books cross-reference."
            )
        record = dict(creator_payload)
        record["Customer_Name"] = {"ID": customer_id}
        record["Record_ID"] = creator_id
        record["Payment_ID"] = creator_payment_id
        try:
            return self._reconcile_collection(record, bank_transaction, source="Manual_Analytics")
        except Exception as exc:
            self._audit(creator_id, "manual_resolution", str(exc), bank_transaction)
            raise

    def _audit(
        self,
        creator_record_id: Optional[str],
        stage: str,
        message: str,
        payload: Any,
    ) -> None:
        logger.warning(
            "Collection reconciliation audit: record=%s stage=%s message=%s",
            creator_record_id,
            stage,
            message,
        )
        if self.config.dry_run or not self.config.audit_form_link_name:
            return
        data = {
            "Creator_Record_ID": creator_record_id or "",
            "Stage": stage,
            "Message": message,
            "Payload": json.dumps(payload, default=str, separators=(",", ":")),
            "Occurred_At": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.creator.add_records(
                self.config.creator_app_link_name,
                self.config.audit_form_link_name,
                {"data": [data]},
            )
        except Exception:
            logger.exception("Unable to persist reconciliation audit record.")


def reconcile_collections(
    creator_client: Any,
    books_client: Any,
    config: CollectionReconciliationConfig,
    analytics_client: Optional[Any] = None,
    validate_schema: bool = True,
    create_missing_books_fields: bool = False,
) -> Dict[str, Any]:
    reconciler = CollectionReconciler(
        creator_client=creator_client,
        books_client=books_client,
        analytics_client=analytics_client,
        config=config,
    )
    if validate_schema:
        reconciler.validate_schema(
            create_missing_books_fields=create_missing_books_fields,
        )
    return reconciler.reconcile_pending()
