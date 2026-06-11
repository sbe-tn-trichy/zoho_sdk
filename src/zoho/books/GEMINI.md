# Folder Index: `zoho/books`

Zoho Books API client integration.

## Client Class: [ZohoBooksAPI](file:///d:/workplace/zoho_sdk/src/zoho/books/client.py#L33)

- `__init__(self, access_token: str, organization_id: str, domain: str = "com", on_request_completed: Optional[Any] = None, token_refresh_callback: Optional[Any] = None)`
- `request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

## Files

| File | Description |
| :--- | :--- |
| [__init__.py](file:///d:/workplace/zoho_sdk/src/zoho/books/__init__.py) | Package initialization. |
| [base.py](file:///d:/workplace/zoho_sdk/src/zoho/books/base.py) | [BaseResource](file:///d:/workplace/zoho_sdk/src/zoho/books/base.py#L4): list, list_all, get, create, update, delete |
| [client.py](file:///d:/workplace/zoho_sdk/src/zoho/books/client.py) | Main [ZohoBooksAPI](file:///d:/workplace/zoho_sdk/src/zoho/books/client.py#L33) client class. |
| [exceptions.py](file:///d:/workplace/zoho_sdk/src/zoho/books/exceptions.py) | [ZohoBooksError](file:///d:/workplace/zoho_sdk/src/zoho/books/exceptions.py#L1) exception. |
| [mixins.py](file:///d:/workplace/zoho_sdk/src/zoho/books/mixins.py) | Common operations mixins: ActiveInactiveMixin, StatusMixin, ApprovalMixin, EmailMixin, CreditsMixin |

## Subfolders

| Folder | Description |
| :--- | :--- |
| [resources/](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/GEMINI.md) | Zoho Books resource modules (Invoices, Estimates, Contacts, items, etc.). |
