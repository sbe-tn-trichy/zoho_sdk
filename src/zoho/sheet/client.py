import logging
import json
from typing import List, Dict, Any, Optional
from zoho.base_client import BaseZohoClient

class ZohoSheetAPI(BaseZohoClient):
    """
    Client for Zoho Sheet API v2.
    Docs: https://www.zoho.com/sheet/help/api/v2/
    """
    def __init__(self, access_token: str, domain: str = "in"):
        base_url = f"https://sheet.zoho.{domain or 'in'}/api/v2"
        super().__init__(
            access_token=access_token,
            domain=domain or "in",
            base_url=base_url,
            service_name="sheet"
        )

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {str(self.access_token)}"
        }

    def list_workbooks(self) -> List[Dict[str, Any]]:
        """Lists all workbooks in the user's account."""
        params = {"method": "workbook.list"} # Added required method param
        res = self.request("GET", "workbooks", params=params)
        return res.get('workbooks', [])

    def list_sheets(self, workbook_id: str) -> List[Dict[str, Any]]:
        """Lists all worksheets in a workbook."""
        params = {"method": "worksheet.list"}
        res = self.request("POST", workbook_id, params=params)
        return res.get('worksheet_names', [])

    def get_rows(self, workbook_id: str, sheet_name: str, limit: int = 1) -> List[Any]:
        """Fetches rows from a specific sheet. Returns empty list if sheet has no records."""
        params = {
            "method": "worksheet.records.fetch",
            "worksheet_name": sheet_name,
            "limit": limit
        }
        try:
            res = self.request("GET", workbook_id, params=params)
            return res.get('records', [])
        except Exception as e:
            if "2884" in str(e):
                return []
            raise

    def set_content(self, workbook_id: str, sheet_name: str, range_addr: str, data: List[List[Any]]) -> Dict[str, Any]:
        """
        Sets content of a range of cells.
        Note: worksheet.content.set is currently returning 2867 (unsupported) in some environments.
        Use set_cell for individual headers if this fails.
        """
        params = {"method": "worksheet.content.set"}
        payload = {
            "worksheet_name": sheet_name,
            "range": range_addr,
            "json_data": json.dumps(data)
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)

    def set_cell(self, workbook_id: str, sheet_name: str, row: int, col: int, content: Any) -> Dict[str, Any]:
        """Sets content of a single cell using cell.content.set (guaranteed to work in v2)."""
        params = {"method": "cell.content.set"}
        payload = {
            "worksheet_name": sheet_name,
            "row": row,
            "column": col,
            "content": str(content)
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)

    def add_sheet(self, workbook_id: str, sheet_name: str) -> Dict[str, Any]:
        """Adds a new sheet to an existing workbook."""
        params = {"method": "worksheet.add"}
        payload = {
            "worksheet_name": sheet_name
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)

    def add_rows(self, workbook_id: str, sheet_name: str, rows_data: Any, header_row: int = 1) -> Dict[str, Any]:
        """
        Appends rows to a specific sheet using tabular records API.
        rows_data can be a list of lists or a list of dicts.
        """
        params = {"method": "worksheet.records.add"}
        payload = {
            "worksheet_name": sheet_name,
            "json_data": json.dumps(rows_data),
            "header_row": header_row
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)

    def update_rows(self, workbook_id: str, sheet_name: str, criteria: str, rows_data: Dict[str, Any]) -> Dict[str, Any]:
        """Updates rows matching a criteria."""
        params = {"method": "worksheet.records.update"}
        payload = {
            "worksheet_name": sheet_name,
            "criteria": criteria,
            "json_data": json.dumps(rows_data)
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)

    def truncate_sheet(self, workbook_id: str, sheet_name: str, criteria: str = "(row_index != 0)") -> Dict[str, Any]:
        """Deletes rows in a sheet based on criteria."""
        params = {"method": "worksheet.records.delete"}
        payload = {
            "worksheet_name": sheet_name,
            "criteria": criteria
        }
        return self.request("POST", workbook_id, params=params, data=payload, is_mutation=True)
