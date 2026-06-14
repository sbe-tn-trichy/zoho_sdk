import logging
import os
from typing import Any, Dict, List, Optional, Union
from zoho.base_client import BaseZohoClient
from .exceptions import ZohoCreatorError

class ZohoCreatorAPI(BaseZohoClient):
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
        base_url = f"https://www.zohoapis.{domain or 'com'}/creator/v2.1"
        super().__init__(
            access_token=access_token,
            domain=domain or "com",
            base_url=base_url,
            service_name="creator",
            token_refresh_callback=token_refresh_callback,
            default_timeout=30
        )
        self.account_owner_name = account_owner_name
        self.environment = environment or "production"

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None
    ) -> Any:
        req_headers = {"environment": self.environment}
        if headers:
            req_headers.update(headers)
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            params=params,
            headers=req_headers
        )

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
