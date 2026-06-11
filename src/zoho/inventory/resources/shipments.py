from typing import Any, Dict
from ..base import BaseResource

class Shipments(BaseResource):
    """Resource class for Zoho Inventory Shipment Orders operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'shipmentorders')

    def mark_as_delivered(self, shipment_id: str) -> Dict[str, Any]:
        """Mark a shipment order status as delivered."""
        return self._action('POST', shipment_id, 'status/delivered')
