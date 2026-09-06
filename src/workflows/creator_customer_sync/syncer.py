import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from zoho.helpers.custom_fields import get_custom_field_value

from ..core.exceptions import ReconciliationError
from .config import CreatorCustomerSyncConfig

logger = logging.getLogger(__name__)


class CreatorCustomerSyncer:
    """Reconciles mapped customer fields from Books into Creator.
    """

    def __init__(
        self,
        books_client: Any,
        creator_client: Any,
        config: CreatorCustomerSyncConfig,
    ) -> None:
        self.books_client = books_client
        self.creator_client = creator_client
        self.config = config

    @staticmethod
    def field_value(record: Dict[str, Any], field: str) -> Any:
        return next((v for k, v in record.items() if k.lower() == field.lower()), None)

    def fetch_books_customers(self) -> Dict[str, Dict[str, Any]]:
        if self.config.books_status_filter not in {"all", "active", "inactive"}:
            raise ReconciliationError("books_status_filter must be all, active, or inactive.")
        records = self.books_client.contacts.list_all(
            params={"contact_type": "customer", "filter_by": "Status.All"},
            resource_key="contacts",
        )
        if not isinstance(records, list):
            raise ReconciliationError("Invalid Books customer response.")
        customers = {}
        for record in records:
            if record.get("contact_type") != "customer":
                continue
            key = str(record.get(self.config.books_id_field) or "").strip()
            if not key or key in customers:
                raise ReconciliationError("Missing or duplicate Books customer key.")
            customers[key] = record
        self.all_books_customer_keys = set(customers)
        selected = {}
        for key, record in customers.items():
            if self.config.books_status_filter != "all":
                if "status" not in record:
                    raise ReconciliationError("Books customer status is missing.")
                if record["status"] != self.config.books_status_filter:
                    continue
            if self.config.books_branch_name is not None:
                branch = record.get(self.config.books_branch_field)
                if branch is None:
                    branch = get_custom_field_value(record, self.config.books_branch_field)
                if str(branch or "").strip().casefold() != self.config.books_branch_name.strip().casefold():
                    continue
            selected[key] = record
        return selected

    def fetch_books_customer_keys(self) -> Set[str]:
        return set(self.fetch_books_customers())

    def fetch_creator_customers(self) -> List[Dict[str, Any]]:
        """Fetch all customer records from Zoho Creator."""
        logger.info(
            f"Fetching Zoho Creator records from app '{self.config.app_link_name}', report '{self.config.report_link_name}'..."
        )
        records = self.creator_client.get_all_records(
            self.config.app_link_name,
            self.config.report_link_name,
        )
        logger.info(f"Loaded {len(records)} records from Zoho Creator.")
        return records

    def identify_orphaned_records(
        self, creator_records: List[Dict[str, Any]], valid_books_keys: Set[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Separate Creator records into orphaned (missing in Books) and matched records."""
        orphaned: List[Dict[str, Any]] = []
        matched: List[Dict[str, Any]] = []

        for record in creator_records:
            raw_val = record.get(self.config.creator_id_field)
            if raw_val is None:
                # Case-insensitive fallback lookup for field names like Customer_Id / Customer_ID / customer_id
                target_lower = self.config.creator_id_field.lower()
                for k, v in record.items():
                    if k.lower() == target_lower:
                        raw_val = v
                        break

            clean_val = str(raw_val).strip() if raw_val is not None else ""

            if not clean_val or clean_val not in valid_books_keys:
                orphaned.append(record)
            else:
                matched.append(record)


        logger.info(
            f"Reconciliation analysis: {len(matched)} matched, {len(orphaned)} orphaned (candidates for deletion)."
        )
        return orphaned, matched

    def verify_safety_thresholds(
        self, total_creator_records: int, candidate_delete_count: int
    ) -> None:
        """Verify that candidate deletion count does not exceed configured safety limits."""
        if candidate_delete_count > self.config.max_deletion_limit:
            raise ReconciliationError(
                f"Safety Threshold Exceeded: Candidate deletion count ({candidate_delete_count}) "
                f"exceeds maximum allowed limit ({self.config.max_deletion_limit}). Aborting execution."
            )

        if total_creator_records > 0:
            deletion_percentage = (candidate_delete_count / total_creator_records) * 100.0
            if deletion_percentage > self.config.max_deletion_percentage:
                raise ReconciliationError(
                    f"Safety Threshold Exceeded: Candidate deletion percentage ({deletion_percentage:.2f}%) "
                    f"exceeds maximum allowed limit ({self.config.max_deletion_percentage:.2f}%). Aborting execution."
                )

    def execute_sync(self) -> Dict[str, Any]:
        """Plan all changes, validate safety, then apply creates, updates and deletes."""
        books = self.fetch_books_customers()
        records = self.fetch_creator_customers()
        if not isinstance(records, list):
            raise ReconciliationError("Invalid Creator customer response.")
        indexed = {}
        for record in records:
            key = str(self.field_value(record, self.config.creator_id_field) or "").strip()
            record_id = record.get("ID") or record.get("id")
            if not key or not record_id or key in indexed:
                raise ReconciliationError("Missing Creator record ID/customer key or duplicate customer key.")
            indexed[key] = record

        mapping = dict(self.config.field_mapping)
        mapping[self.config.creator_id_field] = self.config.books_id_field
        changes = []
        unchanged = 0
        for key, customer in books.items():
            # List responses may omit fields that are only available on the detail endpoint.
            if any(source not in customer for source in mapping.values()):
                detail = self.books_client.contacts.get(str(customer["contact_id"]))
                if not isinstance(detail, dict) or not isinstance(detail.get("contact"), dict):
                    raise ReconciliationError("Invalid Books customer detail response.")
                customer = detail["contact"]
            missing = [source for source in mapping.values() if source not in customer]
            if missing:
                raise ReconciliationError(f"Books customer is missing mapped fields: {missing}")
            payload = {target: customer[source] for target, source in mapping.items()}
            payload[self.config.creator_id_field] = key
            existing = indexed.get(key)
            if existing is None:
                changes.append({"operation": "CREATE", "customer_key": key, "payload": payload})
                continue
            changed = {field: value for field, value in payload.items()
                       if self.field_value(existing, field) != value
                       and not (field == self.config.creator_id_field
                                and str(self.field_value(existing, field)).strip() == value)}
            if changed:
                changes.append({"operation": "UPDATE", "customer_key": key,
                                "creator_record_id": str(existing.get("ID") or existing.get("id")),
                                "payload": changed})
            else:
                unchanged += 1
        for key, record in indexed.items():
            if key not in self.all_books_customer_keys:
                changes.append({"operation": "DELETE", "customer_key": key,
                                "creator_record_id": str(record.get("ID") or record.get("id"))})
        counts = {op: sum(c["operation"] == op for c in changes) for op in ("CREATE", "UPDATE", "DELETE")}
        self.verify_safety_thresholds(len(records), counts["DELETE"])
        if counts["CREATE"] and not self.config.form_link_name:
            raise ReconciliationError("form_link_name is required to create missing Creator customers.")
        for change in changes:
            operation = change["operation"]
            if self.config.dry_run:
                change["action"] = "WOULD_" + operation
                continue
            if operation == "CREATE":
                self.creator_client.add_records(self.config.app_link_name, self.config.form_link_name,
                                                payload={"data": [change["payload"]]})
                change["action"] = "CREATED"
            elif operation == "UPDATE" or self.config.soft_delete_field:
                payload = change["payload"] if operation == "UPDATE" else {
                    self.config.soft_delete_field: self.config.soft_delete_value}
                self.creator_client.update_records(self.config.app_link_name, self.config.report_link_name,
                                                   payload={"data": payload}, record_id=change["creator_record_id"])
                change["action"] = "UPDATED" if operation == "UPDATE" else "SOFT_DELETED"
            else:
                self.creator_client.delete_records(self.config.app_link_name, self.config.report_link_name,
                                                   record_id=change["creator_record_id"])
                change["action"] = "HARD_DELETED"
        timestamp = datetime.now(timezone.utc)
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"creator_customer_sync_{timestamp:%Y%m%d_%H%M%S_%f}.json"
        summary = {
            "timestamp": timestamp.isoformat(), "dry_run": self.config.dry_run,
            "scanned_books_customer_keys_count": len(books), "scanned_creator_records_count": len(records),
            "books_status_filter": self.config.books_status_filter,
            "books_branch_name": self.config.books_branch_name,
            "all_books_customer_keys_count": len(self.all_books_customer_keys),
            "excluded_creator_records_count": len((set(indexed) & self.all_books_customer_keys) - set(books)),
            "matched_records_count": len(set(books) & set(indexed)), "unchanged_count": unchanged,
            "records": changes, "report_file": str(report_path),
        }
        for operation, past in (("CREATE", "created"), ("UPDATE", "updated"), ("DELETE", "deleted")):
            summary[f"candidate_{operation.lower()}_count"] = counts[operation]
            summary[f"{past}_count"] = 0 if self.config.dry_run else counts[operation]
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
