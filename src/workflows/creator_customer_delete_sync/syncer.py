import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from zoho.exceptions import ZohoError
from ..core.exceptions import ReconciliationError
from .config import CreatorCustomerDeleteSyncConfig

logger = logging.getLogger(__name__)


class CreatorCustomerDeleteSyncer:
    """Orchestrates deletion reconciliation between Zoho Creator and Zoho Books.

    Deletes Creator customer records that no longer exist in Zoho Books.
    """

    def __init__(
        self,
        books_client: Any,
        creator_client: Any,
        config: CreatorCustomerDeleteSyncConfig,
    ) -> None:
        self.books_client = books_client
        self.creator_client = creator_client
        self.config = config

    def fetch_books_customer_keys(self) -> Set[str]:
        """Fetch all customer contact keys from Zoho Books."""
        logger.info(
            f"Fetching Zoho Books customer contacts (status filter: {self.config.books_status_filter})..."
        )
        params = {
            "contact_type": "customer",
            "status": self.config.books_status_filter,
        }
        contacts = self.books_client.contacts.list_all(params=params, resource_key="contacts")
        
        books_keys: Set[str] = set()
        for contact in contacts:
            if self.config.books_id_field == "contact_id":
                val = contact.get("contact_id")
            elif self.config.books_id_field in contact:
                val = contact.get(self.config.books_id_field)
            else:
                # Check custom fields if configured
                val = None
                for cf in contact.get("custom_fields", []):
                    if cf.get("api_name") == self.config.books_id_field or cf.get("label") == self.config.books_id_field:
                        val = cf.get("value")
                        break
            
            if val is not None and str(val).strip():
                books_keys.add(str(val).strip())
        
        logger.info(f"Loaded {len(books_keys)} unique customer keys from Zoho Books.")
        return books_keys

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
        """Execute full deletion reconciliation pipeline."""
        books_keys = self.fetch_books_customer_keys()
        creator_records = self.fetch_creator_customers()

        orphaned_records, matched_records = self.identify_orphaned_records(
            creator_records, books_keys
        )

        total_creator = len(creator_records)
        candidate_count = len(orphaned_records)

        # Enforce safety check before proceeding
        self.verify_safety_thresholds(total_creator, candidate_count)

        deleted_records_info: List[Dict[str, Any]] = []
        
        if self.config.dry_run:
            logger.info("DRY RUN ENABLED: No records will be deleted in Zoho Creator.")
            for rec in orphaned_records:
                rec_id = rec.get("ID") or rec.get("id") or "UNKNOWN_ID"
                key_val = rec.get(self.config.creator_id_field)
                deleted_records_info.append(
                    {
                        "creator_record_id": rec_id,
                        "creator_id_field_value": key_val,
                        "action": "WOULD_DELETE",
                        "reason": "Not found in Zoho Books",
                    }
                )
        else:
            logger.info(f"Executing deletions for {candidate_count} orphaned Creator records...")
            for rec in orphaned_records:
                rec_id = rec.get("ID") or rec.get("id")
                if not rec_id:
                    logger.warning(f"Skipping record missing 'ID': {rec}")
                    continue

                if self.config.soft_delete_field:
                    payload = {self.config.soft_delete_field: self.config.soft_delete_value}
                    self.creator_client.update_records(
                        self.config.app_link_name,
                        self.config.report_link_name,
                        payload=payload,
                        record_id=str(rec_id),
                    )
                    action = "SOFT_DELETED"
                else:
                    self.creator_client.delete_records(
                        self.config.app_link_name,
                        self.config.report_link_name,
                        record_id=str(rec_id),
                    )
                    action = "HARD_DELETED"

                deleted_records_info.append(
                    {
                        "creator_record_id": rec_id,
                        "creator_id_field_value": rec.get(self.config.creator_id_field),
                        "action": action,
                        "reason": "Not found in Zoho Books",
                    }
                )

        # Prepare summary audit report
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.config.output_dir / f"creator_customer_delete_sync_{timestamp}.json"

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.config.dry_run,
            "app_link_name": self.config.app_link_name,
            "report_link_name": self.config.report_link_name,
            "scanned_books_customer_keys_count": len(books_keys),
            "scanned_creator_records_count": total_creator,
            "matched_records_count": len(matched_records),
            "candidate_delete_count": candidate_count,
            "deleted_count": len(deleted_records_info),
            "records": deleted_records_info,
            "report_file": str(report_path),
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Reconciliation audit report saved to {report_path}")
        return summary
