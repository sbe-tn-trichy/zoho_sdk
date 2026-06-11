from typing import Any, Dict
from ..base import BaseResource

class Batches(BaseResource):
    """Resource class for Zoho Inventory Batches operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'batches')

    def mark_as_active(self, batch_id: str) -> Dict[str, Any]:
        """Mark a batch as active."""
        return self._action('POST', batch_id, 'active')

    def mark_as_inactive(self, batch_id: str) -> Dict[str, Any]:
        """Mark a batch as inactive."""
        return self._action('POST', batch_id, 'inactive')
