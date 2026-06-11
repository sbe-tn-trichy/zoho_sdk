# Folder Index: `zoho/inventory`

Zoho Inventory API client integration.

## Client Class: [ZohoInventoryAPI](file:///d:/workplace/zoho_sdk/src/zoho/inventory/client.py#L33)

- `__init__(self, access_token: str, organization_id: str, domain: str = "com", on_request_completed: Optional[Any] = None, token_refresh_callback: Optional[Any] = None)`
- `request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

## Files

| File | Description |
| :--- | :--- |
| [__init__.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/__init__.py) | Package initialization. |
| [base.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/base.py) | [BaseResource](file:///d:/workplace/zoho_sdk/src/zoho/inventory/base.py#L4): list, list_all, get, create, update, delete |
| [client.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/client.py) | Main [ZohoInventoryAPI](file:///d:/workplace/zoho_sdk/src/zoho/inventory/client.py#L33) client class. |
| [exceptions.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/exceptions.py) | [ZohoInventoryError](file:///d:/workplace/zoho_sdk/src/zoho/inventory/exceptions.py#L1) exception. |

## Subfolders

| Folder | Description |
| :--- | :--- |
| [resources/](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/GEMINI.md) | Zoho Inventory resource modules (Items, Move Orders, Transfer Orders, Inventory Adjustments, Packages, Shipments, Picklists, Bins, Batches). |
