from typing import Any
from ..base import BaseResource

class Packages(BaseResource):
    """Resource class for Zoho Inventory Packages operations."""
    def __init__(self, client: Any):
        super().__init__(client, 'packages')
