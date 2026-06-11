# Folder Index: `zoho/wd/resources`

Zoho Workdrive Resource modules mapping to specific API endpoints.

## Files and Available Classes/Methods

### [files.py](file:///d:/workplace/zoho_sdk/src/zoho/wd/resources/files.py)
- **[Files](file:///d:/workplace/zoho_sdk/src/zoho/wd/resources/files.py#L15)** (inherits `BaseResource` from `wd/base.py`)
  - `list_files(self, folder_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
  - `list_all_files(self, folder_id: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]`
  - `download(self, file_id: str, save_path: str, source_folder_id: str = None) -> None`
  - `download_folder(self, folder_id: str, destination: os.PathLike[str] | str, *, dry_run: bool = False) -> List[Path]`
  - `move(self, file_id: str, destination_folder_id: str) -> Dict[str, Any]`
  - `create_folder(self, name: str, parent_id: str) -> Dict[str, Any]`
  - `delete(self, resource_id: str) -> Dict[str, Any]`
  - `search(self, name: str, parent_id: Optional[str] = None, resource_type: Optional[str] = "folder") -> List[Dict[str, Any]]`
  - `upload(self, folder_id: str, file_path: str, file_name: Optional[str] = None) -> Dict[str, Any]`
  - `get_base_name(self, name: str) -> str`
  - `merge_folders(self, source_id: str, target_id: str, folder_name: str) -> None`
  - `cleanup_duplicates(self, parent_id: str, recursive: bool = True) -> None`
