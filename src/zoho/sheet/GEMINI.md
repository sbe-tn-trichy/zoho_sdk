# Folder Index: `zoho/sheet`

Zoho Sheet API client integration.

## Client Class: [ZohoSheetAPI](file:///d:/workplace/zoho_sdk/src/zoho/sheet/client.py#L9)

- `__init__(self, access_token: str, domain: str = "in")`
- `list_workbooks(self) -> List[Dict[str, Any]]`
- `list_sheets(self, workbook_id: str) -> List[Dict[str, Any]]`
- `get_rows(self, workbook_id: str, sheet_name: str, limit: int = 1) -> List[Any]`
- `set_content(self, workbook_id: str, sheet_name: str, range_addr: str, data: List[List[Any]]) -> Dict[str, Any]`
- `set_cell(self, workbook_id: str, sheet_name: str, row: int, col: int, content: Any) -> Dict[str, Any]`
- `add_sheet(self, workbook_id: str, sheet_name: str) -> Dict[str, Any]`
- `add_rows(self, workbook_id: str, sheet_name: str, rows_data: Any, header_row: int = 1) -> Dict[str, Any]`
- `update_rows(self, workbook_id: str, sheet_name: str, criteria: str, rows_data: Dict[str, Any]) -> Dict[str, Any]`
- `truncate_sheet(self, workbook_id: str, sheet_name: str, criteria: str = "(row_index != 0)") -> Dict[str, Any]`

## Files

| File | Description |
| :--- | :--- |
| [__init__.py](file:///d:/workplace/zoho_sdk/src/zoho/sheet/__init__.py) | Package initialization. |
| [client.py](file:///d:/workplace/zoho_sdk/src/zoho/sheet/client.py) | Main [ZohoSheetAPI](file:///d:/workplace/zoho_sdk/src/zoho/sheet/client.py#L9) client implementation. |
