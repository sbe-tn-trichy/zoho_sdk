from typing import Any, Dict
from ..base import BaseResource

class ItemGroups(BaseResource):
    """Resource class for Zoho Inventory Item Groups operations."""
    
    def __init__(self, client: Any):
        super().__init__(client, 'itemgroups')

    def mark_as_active(self, itemgroup_id: str) -> Dict[str, Any]:
        """Mark an item group status as active."""
        return self._action('POST', itemgroup_id, 'active')

    def mark_as_inactive(self, itemgroup_id: str) -> Dict[str, Any]:
        """Mark an item group status as inactive."""
        return self._action('POST', itemgroup_id, 'inactive')
