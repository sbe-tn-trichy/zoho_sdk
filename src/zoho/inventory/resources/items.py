from typing import Any
from ..base import BaseResource

class Items(BaseResource):
    """Resource class for Zoho Inventory Items operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'items')
