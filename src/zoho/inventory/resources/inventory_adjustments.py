from typing import Any
from ..base import BaseResource

class InventoryAdjustments(BaseResource):
    """Resource class for Zoho Inventory Adjustments operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'inventoryadjustments')
