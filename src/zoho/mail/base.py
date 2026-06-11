from typing import Any, Dict, Optional, List, Union
from .exceptions import ZohoMailError

class BaseResource:
    """Base class for Zoho Mail modules providing standard CRUD operations."""
    required_fields: List[str] = []
    defaults: Dict[str, Any] = {}

    def __init__(self, client: Any, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def _prepare_payload(self, data: Dict[str, Any], check_required: bool = True) -> Dict[str, Any]:
        """Merge defaults (if creating) and check if all required fields are present."""
        if check_required:
            payload = {**self.defaults, **data}
        else:
            payload = data.copy()
        
        if check_required:
            missing = [field for field in self.required_fields if field not in payload]
            if missing:
                raise ZohoMailError(f"Missing required fields: {', '.join(missing)}")
            
        return payload

    def list(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.request('GET', self.endpoint, params=params)

    def get(self, resource_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.request('GET', f"{self.endpoint}/{resource_id}", params=params)

    def create(self, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = self._prepare_payload(data, check_required=True)
        return self.client.request('POST', self.endpoint, json=payload, params=params, files=files)

    def update(self, resource_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = self._prepare_payload(data, check_required=False)
        return self.client.request('PUT', f"{self.endpoint}/{resource_id}", json=payload, params=params, files=files)

    def delete(self, resource_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.request('DELETE', f"{self.endpoint}/{resource_id}", params=params)

    def _action(self, method: str, resource_id: Optional[str], action: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Helper for action endpoints."""
        url = f"{self.endpoint}/{resource_id}/{action}" if resource_id else f"{self.endpoint}/{action}"
        return self.client.request(method, url, json=data, params=params)
