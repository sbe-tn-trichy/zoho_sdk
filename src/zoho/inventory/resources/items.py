from typing import Any, Dict
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
