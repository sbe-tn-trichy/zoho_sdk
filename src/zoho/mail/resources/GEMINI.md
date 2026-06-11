# Folder Index: `zoho/mail/resources`

Zoho Mail Resource modules mapping to specific API endpoints.

## Files and Available Classes/Methods

### [accounts.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/accounts.py)
- **[Accounts](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/accounts.py#L3)** (inherits `BaseResource` from `mail/base.py`)
  - Standard CRUD: `list()`, `get()`, `create()`, `update()`, `delete()`

### [folders.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/folders.py)
- **[Folders](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/folders.py#L4)** (inherits `BaseResource` from `mail/base.py`)
  - `create(self, folder_name: str, parent_folder_id: Optional[str] = None) -> Dict[str, Any]`
  - `rename(self, folder_id: str, new_name: str) -> Dict[str, Any]`

### [messages.py](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/messages.py)
- **[Messages](file:///d:/workplace/zoho_sdk/src/zoho/mail/resources/messages.py#L5)** (inherits `BaseResource` from `mail/base.py`)
  - `list(self, folder_id: Optional[str] = None, page: int = 1, limit: int = 50, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
  - `get_content(self, message_id: str) -> Dict[str, Any]`
  - `send(self, from_address: str, to_address: str, subject: str, content: str, **kwargs) -> Dict[str, Any]`
  - `save_draft(self, from_address: str, to_address: str, subject: str, content: str, **kwargs) -> Dict[str, Any]`
  - `mark_as_read(self, message_id: str) -> Dict[str, Any]`
  - `mark_as_unread(self, message_id: str) -> Dict[str, Any]`
  - `get_attachments_info(self, folder_id: str, message_id: str) -> Dict[str, Any]`
  - `get_attachment_content(self, folder_id: str, message_id: str, attachment_id: str) -> bytes`
  - `download_attachment(self, folder_id: str, message_id: str, attachment_id: str, download_path: str) -> str`
  - `list_iter(self, folder_id: Optional[str] = None, start: int = 1, limit: int = 50)`
  - `message_has_attachment(self, message: Dict[str, Any]) -> bool`
  - `extract_attachments(self, response: Dict[str, Any]) -> List[Dict[str, Any]]`
  - `resolve_download_path(self, download_dir: str, attachment_name: str, sequence_index: Optional[int] = None) -> str`
  - `download_folder_attachments(self, folder_id: str, download_dir: str, filename: Optional[str] = None) -> List[str]`
