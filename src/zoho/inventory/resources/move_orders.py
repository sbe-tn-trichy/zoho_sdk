from typing import Any, Dict
from ..base import BaseResource

class MoveOrders(BaseResource):
    """Resource class for Zoho Inventory Move Orders operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'moveorders')

    def mark_as_confirmed(self, move_order_id: str) -> Dict[str, Any]:
        """Mark a move order status as confirmed."""
        return self._action('POST', move_order_id, 'status/confirmed')

    def mark_as_in_progress(self, move_order_id: str) -> Dict[str, Any]:
        """Mark a move order status as in progress."""
        return self._action('POST', move_order_id, 'status/inprogress')

    def mark_as_completed(self, move_order_id: str) -> Dict[str, Any]:
        """Mark a move order status as completed."""
        return self._action('POST', move_order_id, 'status/completed')
