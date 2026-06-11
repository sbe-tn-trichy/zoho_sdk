# Folder Index: `zoho/mail`

Zoho Mail API client integration.

## Client Class: [ZohoMailAPI](file:///d:/workplace/zoho_sdk/src/zoho/mail/client.py#L27)

- `__init__(self, access_token: str, domain: str = "com")`
- `account(self, account_id: str) -> AccountScope`
- `request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, stream: bool = False) -> Any`

## Files

| File | Description |
| :--- | :--- |
| [__init__.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/__init__.py) | Package initialization. |
| [base.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/base.py) | [BaseResource](file:///d:/workplace/zoho_sdk/src/zoho/mail/base.py#L4): list, get, create, update, delete, _action |
| [client.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/client.py) | Main [ZohoMailAPI](file:///d:/workplace/zoho_sdk/src/zoho/mail/client.py#L27) client implementation. |
| [exceptions.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/exceptions.py) | [ZohoMailError](file:///d:/workplace/zoho_sdk/src/zoho/mail/exceptions.py#L1) exception. |

## Subfolders

| Folder | Description |
| :--- | :--- |
| [resources/](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/GEMINI.md) | Zoho Mail resource modules (Accounts, Folders, Messages). |
