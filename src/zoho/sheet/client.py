import logging
import requests
import json
from typing import List, Dict, Any, Optional
from typing import List, Dict, Any, Optional

logger = logging.getLogger("zoho_sheet")

class ZohoSheetAPI:
    """
    Client for Zoho Sheet API v2.
    Docs: https://www.zoho.com/sheet/help/api/v2/
    """
    def __init__(self, access_token: str, domain: str = "in"):
        self.access_token = access_token
        self.domain = domain or "in"
        self.base_url = f"https://sheet.zoho.{self.domain}/api/v2"

    def _get_headers(self):
        return {
            "Authorization": f"Zoho-oauthtoken {self.access_token}"
        }

    def list_workbooks(self) -> List[Dict[str, Any]]:
        """Lists all workbooks in the user's account."""
        url = f"{self.base_url}/workbooks"
        params = {"method": "workbook.list"} # Added required method param
        response = requests.get(url, headers=self._get_headers(), params=params)
        if response.status_code != 200:
            logger.error(f"Error listing workbooks: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json().get('workbooks', [])

    def list_sheets(self, workbook_id: str) -> List[Dict[str, Any]]:
        """Lists all worksheets in a workbook."""
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.list"}
        response = requests.post(url, headers=self._get_headers(), params=params)
        if response.status_code != 200:
            logger.error(f"Error listing sheets: {response.status_code} - {response.text}")
        response.raise_for_status()
        res_data = response.json()
        return res_data.get('worksheet_names', [])

    def get_rows(self, workbook_id: str, sheet_name: str, limit: int = 1) -> List[Any]:
        """Fetches rows from a specific sheet. Returns empty list if sheet has no records."""
        url = f"{self.base_url}/{workbook_id}"
        params = {
            "method": "worksheet.records.fetch",
            "worksheet_name": sheet_name,
            "limit": limit
        }
        response = requests.get(url, headers=self._get_headers(), params=params)
        if response.status_code != 200:
            # Handle error 2884 (No records/headers found) gracefully
            try:
                err_data = response.json()
                if err_data.get('error_code') == 2884:
                    return []
            except:
                pass
            logger.error(f"Error fetching records: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json().get('records', [])

    def set_content(self, workbook_id: str, sheet_name: str, range_addr: str, data: List[List[Any]]) -> Dict[str, Any]:
        """
        Sets content of a range of cells.
        Note: worksheet.content.set is currently returning 2867 (unsupported) in some environments.
        Use set_cell for individual headers if this fails.
        """
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.content.set"}
        payload = {
            "worksheet_name": sheet_name,
            "range": range_addr,
            "json_data": json.dumps(data)
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        if response.status_code != 200:
            logger.error(f"Error setting content: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json()

    def set_cell(self, workbook_id: str, sheet_name: str, row: int, col: int, content: Any) -> Dict[str, Any]:
        """Sets content of a single cell using cell.content.set (guaranteed to work in v2)."""
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "cell.content.set"}
        payload = {
            "worksheet_name": sheet_name,
            "row": row,
            "column": col,
            "content": str(content)
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        response.raise_for_status()
        return response.json()

    def add_sheet(self, workbook_id: str, sheet_name: str) -> Dict[str, Any]:
        """Adds a new sheet to an existing workbook."""
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.add"}
        payload = {
            "worksheet_name": sheet_name
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        response.raise_for_status()
        return response.json()

    def add_rows(self, workbook_id: str, sheet_name: str, rows_data: Any, header_row: int = 1) -> Dict[str, Any]:
        """
        Appends rows to a specific sheet using tabular records API.
        rows_data can be a list of lists or a list of dicts.
        """
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.records.add"}
        
        payload = {
            "worksheet_name": sheet_name,
            "json_data": json.dumps(rows_data),
            "header_row": header_row
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        if response.status_code not in [200, 201]:
            logger.error(f"Error adding rows: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json()

    def update_rows(self, workbook_id: str, sheet_name: str, criteria: str, rows_data: Dict[str, Any]) -> Dict[str, Any]:
        """Updates rows matching a criteria."""
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.records.update"}
        payload = {
            "worksheet_name": sheet_name,
            "criteria": criteria,
            "json_data": json.dumps(rows_data)
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        response.raise_for_status()
        return response.json()

    def truncate_sheet(self, workbook_id: str, sheet_name: str, criteria: str = "(row_index != 0)") -> Dict[str, Any]:
        """Deletes rows in a sheet based on criteria."""
        url = f"{self.base_url}/{workbook_id}"
        params = {"method": "worksheet.records.delete"}
        payload = {
            "worksheet_name": sheet_name,
            "criteria": criteria
        }
        response = requests.post(url, headers=self._get_headers(), params=params, data=payload)
        if response.status_code != 200:
            logger.error(f"Error truncating sheet: {response.status_code} - {response.text}")
        response.raise_for_status()
        return response.json()
