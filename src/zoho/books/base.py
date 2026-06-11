from typing import Any, Dict, Optional, List, Union, BinaryIO
from .exceptions import ZohoBooksError

class BaseResource:
    """Base class for Zoho Books modules providing standard CRUD operations."""
    required_fields: List[str] = []
    defaults: Dict[str, Any] = {}
    
    # New: Support for line item validation and defaults
    line_item_required_fields: List[str] = []
    line_item_defaults: Dict[str, Any] = {}

    def __init__(self, client: Any, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def _prepare_payload(self, data: Dict[str, Any], check_required: bool = True) -> Dict[str, Any]:
        """Merge defaults (if creating) and check if all required fields are present."""
        # Only merge defaults if we are checking for required fields (i.e., during creation)
        if check_required:
            payload = {**self.defaults, **data}
        else:
            payload = data.copy()
        
        import logging
        logger = logging.getLogger("zoho.books.api")
        # 2. Validate top-level required fields
        if check_required:
            missing = [field for field in self.required_fields if field not in payload]
            if missing:
                logger.error(f"Validation failed. Payload keys: {list(payload.keys())}. Missing: {missing}")
                raise ZohoBooksError(f"Missing required fields: {', '.join(missing)}")

            
        # 3. Handle nested line_items if present
        if "line_items" in payload and isinstance(payload["line_items"], list):
            processed_items = []
            for index, item in enumerate(payload["line_items"]):
                # Apply line item defaults only if creating
                if check_required:
                    full_item = {**self.line_item_defaults, **item}
                else:
                    full_item = item.copy()
                
                # Validate line item required fields if creating
                if check_required:
                    missing_item_fields = [f for f in self.line_item_required_fields if f not in full_item]
                    if missing_item_fields:
                        raise ZohoBooksError(
                            f"Line item {index} missing required fields: {', '.join(missing_item_fields)}"
                        )
                processed_items.append(full_item)
            
            payload["line_items"] = processed_items
            
        return payload

    def list(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.request('GET', self.endpoint, params=params)

    def list_all(self, params: Optional[Dict[str, Any]] = None, resource_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Helper to fetch all records across all pages."""
        all_records = []
        page = 1
        params = params or {}
        
        # Use a default resource key based on endpoint if not provided (e.g., 'bills' for '/bills')
        key = resource_key or self.endpoint.split('/')[-1]
        
        while True:
            current_params = {**params, 'page': page, 'per_page': 200}
            res = self.list(params=current_params)
            records = res.get(key, [])
            all_records.extend(records)
            
            # Check for more pages
            page_context = res.get('page_context', {})
            if not page_context.get('has_more_page', False):
                break
            page += 1
            
        return all_records

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
        """Helper for action endpoints like /invoices/{id}/status/sent"""
        url = f"{self.endpoint}/{resource_id}/{action}" if resource_id else f"{self.endpoint}/{action}"
        return self.client.request(method, url, json=data, params=params)
