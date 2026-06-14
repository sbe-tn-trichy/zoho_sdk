import os
import requests
import logging
from typing import Any, Dict, List, Optional, Union
from .exceptions import ZohoCreatorError

logger = logging.getLogger("zoho_creator")

class ZohoCreatorAPI:
    """
    Client for Zoho Creator API v2.1.
    Docs: https://www.zoho.com/creator/help/api/v2.1/
    """
    def __init__(
        self,
        access_token: str,
        account_owner_name: str,
        domain: str = "com",
        environment: str = "production",
        token_refresh_callback: Optional[Any] = None
    ):
        self.access_token = access_token
        self.account_owner_name = account_owner_name
        self.domain = domain or "com"
        self.environment = environment or "production"
        self.token_refresh_callback = token_refresh_callback
        self.base_url = f"https://www.zohoapis.{self.domain}/creator/v2.1"

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = f"{self.base_url}/{endpoint}"
        
        req_headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "environment": self.environment
        }
        if headers:
            req_headers.update(headers)
            
        logger.info(f"Request: {method} {url} | Params: {params} | Headers: {req_headers}")
        
        response = requests.request(
            method=method,
            url=url,
            headers=req_headers,
            params=params,
            json=json,
            timeout=30
        )
        
        # Automatic refresh once if 401 Unauthorized
        if response.status_code == 401 and self.token_refresh_callback:
            logger.warning("Token expired. Refreshing token...")
            self.access_token = self.token_refresh_callback()
            req_headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
            response = requests.request(
                method=method,
                url=url,
                headers=req_headers,
                params=params,
                json=json,
                timeout=30
            )
            
        if response.status_code not in (200, 201, 202, 204):
            logger.error(f"Request failed: {response.status_code} - {response.text}")
            try:
                err_data = response.json()
                msg = err_data.get("message") or err_data.get("description") or response.text
                code = err_data.get("code")
                raise ZohoCreatorError(f"API Error (code={code}): {msg}")
            except Exception as e:
                if isinstance(e, ZohoCreatorError):
                    raise
                raise ZohoCreatorError(f"HTTP Error {response.status_code}: {response.text}")
                
        if response.status_code == 204:
            return {}
            
        return response.json()

    # ==========================================
    # 1. Native Metadata APIs
    # ==========================================
    def list_applications(self) -> Dict[str, Any]:
        """Gets metadata of all applications."""
        return self.request("GET", f"meta/{self.account_owner_name}/applications")

    def list_forms(self, app_link_name: str) -> Dict[str, Any]:
        """Gets metadata of all forms in an application."""
        return self.request("GET", f"meta/{self.account_owner_name}/{app_link_name}/forms")

    def list_reports(self, app_link_name: str) -> Dict[str, Any]:
        """Gets metadata of all reports in an application."""
        return self.request("GET", f"meta/{self.account_owner_name}/{app_link_name}/reports")

    def get_fields(self, app_link_name: str, form_link_name: str) -> Dict[str, Any]:
        """Gets metadata of all fields in a form."""
        return self.request("GET", f"meta/{self.account_owner_name}/{app_link_name}/form/{form_link_name}/fields")

    # ==========================================
    # 2. Native Data APIs
    # ==========================================
    def get_records(
        self,
        app_link_name: str,
        report_link_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Fetches records from a report (up to 1000 records)."""
        return self.request("GET", f"data/{self.account_owner_name}/{app_link_name}/report/{report_link_name}", params=params)

    def add_records(
        self,
        app_link_name: str,
        form_link_name: str,
        payload: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Adds record(s) to a form (payload format: {"data": [...]})."""
        return self.request("POST", f"data/{self.account_owner_name}/{app_link_name}/form/{form_link_name}", json=payload, params=params)

    def update_records(
        self,
        app_link_name: str,
        report_link_name: str,
        payload: Dict[str, Any],
        record_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Updates record(s) in a report by ID or criteria (payload: {"data": {...}})."""
        endpoint = f"data/{self.account_owner_name}/{app_link_name}/report/{report_link_name}"
        if record_id:
            endpoint = f"{endpoint}/{record_id}"
        return self.request("PATCH", endpoint, json=payload, params=params)

    def delete_records(
        self,
        app_link_name: str,
        report_link_name: str,
        record_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Deletes record(s) in a report by ID or criteria."""
        endpoint = f"data/{self.account_owner_name}/{app_link_name}/report/{report_link_name}"
        if record_id:
            endpoint = f"{endpoint}/{record_id}"
        return self.request("DELETE", endpoint, params=params)

    # ==========================================
    # 3. Custom SDK Functions
    # ==========================================
    def get_all_records(
        self,
        app_link_name: str,
        report_link_name: str,
        criteria: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Custom function: Auto-paginates using record_cursor to fetch all records.
        """
        all_records = []
        params = {"max_records": 1000}
        if criteria:
            params["criteria"] = criteria
            
        res = self.get_records(app_link_name, report_link_name, params=params)
        
        # Check if there is data returned
        data = res.get("data", [])
        all_records.extend(data)
        
        # Loop while cursor exists in the response
        while True:
            cursor = res.get("page_context", {}).get("record_cursor") or res.get("record_cursor")
            if not cursor:
                break
            # Query next page using cursor
            params = {"record_cursor": cursor}
            res = self.get_records(app_link_name, report_link_name, params=params)
            data = res.get("data", [])
            all_records.extend(data)
            if not data:
                break
                
        return all_records

    def add_records_bulk(
        self,
        app_link_name: str,
        form_link_name: str,
        records: List[Dict[str, Any]],
        skip_workflow: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Custom function: Bulk adds records by chunking them into batches of 200.
        """
        responses = []
        # Chunk records in batches of 200
        for i in range(0, len(records), 200):
            chunk = records[i:i+200]
            payload = {"data": chunk}
            if skip_workflow:
                payload["skip_workflow"] = skip_workflow
            res = self.add_records(app_link_name, form_link_name, payload)
            responses.append(res)
        return responses
