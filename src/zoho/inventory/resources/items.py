from typing import Any, Dict, List, Optional
import json
from ..base import BaseResource

class Items(BaseResource):
    """Resource class for Zoho Inventory Items operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'items')

    def group_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Group existing items under a new item group.
        """
        payload = {
            "JSONString": json.dumps(data)
        }
        return self.client.request(
            'POST',
            'items/grouping',
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            data=payload
        )

    def list_by_status(self, status: str = "active") -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if status and status.lower() != "all":
            params["filter_by"] = f"Status.{status.title()}"
        return self.list_all(params=params)

    def list_by_purchase_account(
        self,
        account_id: Optional[str],
        status: str = "all",
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if account_id:
            params["purchase_account_id"] = account_id
        if status and status.lower() != "all":
            params["filter_by"] = f"Status.{status.title()}"
        return self.list_all(params=params)

    def mark_inactive_bulk(
        self,
        item_ids: List[str],
        batch_size: int = 200,
    ) -> List[Dict[str, Any]]:
        if batch_size < 1 or batch_size > 200:
            raise ValueError("batch_size must be between 1 and 200")
        clean_ids = [str(item_id).strip() for item_id in item_ids if str(item_id).strip()]
        responses = []
        for start in range(0, len(clean_ids), batch_size):
            batch_ids = clean_ids[start:start + batch_size]
            response = self.client.request(
                "POST",
                "items/inactive",
                params={"item_ids": ",".join(batch_ids)},
            )
            responses.append({"item_ids": batch_ids, "response": response})
        return responses
