from typing import Any, Dict
from ..base import BaseResource

class TransferOrders(BaseResource):
    """Resource class for Zoho Inventory Transfer Orders operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'transferorders')

    def mark_as_in_transit(self, transfer_order_id: str) -> Dict[str, Any]:
        """Mark a transfer order as in-transit."""
        return self._action('POST', transfer_order_id, 'status/intransit')

    def mark_as_received(self, transfer_order_id: str) -> Dict[str, Any]:
        """Mark a transfer order as received."""
        return self._action('POST', transfer_order_id, 'status/received')

    def submit_for_approval(self, transfer_order_id: str) -> Dict[str, Any]:
        """Submit a transfer order for approval."""
        return self._action('POST', transfer_order_id, 'submit')

    def approve(self, transfer_order_id: str) -> Dict[str, Any]:
        """Approve a transfer order."""
        return self._action('POST', transfer_order_id, 'approve')

    def reject(self, transfer_order_id: str) -> Dict[str, Any]:
        """Reject a transfer order."""
        return self._action('POST', transfer_order_id, 'reject')
