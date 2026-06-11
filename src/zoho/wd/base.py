from typing import Any, Dict, Optional, List, Union, BinaryIO
from .exceptions import ZohoWorkdriveError

class BaseResource:
    """Base class for Zoho Workdrive resources providing standard operations."""
    
    def __init__(self, client: Any, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def _action(self, method: str, resource_id: str, action: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a specific action on a resource."""
        endpoint = f"{self.endpoint}/{resource_id}/{action}" if action else f"{self.endpoint}/{resource_id}"
        return self.client.request(method, endpoint, json=data, params=params)
