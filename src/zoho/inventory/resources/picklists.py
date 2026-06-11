from typing import Any, Dict
from ..base import BaseResource

class Picklists(BaseResource):
    """Resource class for Zoho Inventory Picklists operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'picklists')

    def mark_status(self, picklist_id: str, status: str) -> Dict[str, Any]:
        """Update the status of a picklist."""
        payload = {"status": status}
        return self._action('POST', picklist_id, 'status', data=payload)
