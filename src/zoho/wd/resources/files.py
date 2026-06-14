from pathlib import Path
from typing import Any, Dict, Optional, List
from ..base import BaseResource
import logging
import os
import sys
import re

# Logger setup


app_logger = logging.getLogger("zoho_wd.app")
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

class Files(BaseResource):
    """Resource class for Zoho Workdrive Files operations."""
    
    def __init__(self, client: Any):
        super().__init__(client, "files")

    def list_files(self, folder_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """List files and folders within a specific folder."""
        app_logger.info(f"Listing files in folder: {folder_id} with params: {params}")
        endpoint = f"files/{folder_id}/files"
        return self.client.request('GET', endpoint, params=params)

    def list_all_files(self, folder_id: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetch all files and folders across all pages using limit/offset pagination."""
        all_data = []
        page_limit = 100 # WorkDrive limit is often 50 or 100
        offset = 0
        params = params or {}
        while True:
            current_params = {**params, "page[limit]": page_limit, "page[offset]": offset}
            res = self.list_files(folder_id, params=current_params)
            data = res.get('data', [])
            all_data.extend(data)
            
            # Check if there are more pages
            if len(data) < page_limit:
                break
                
            offset += page_limit
        return all_data

    def download(self, file_id: str, save_path: str, source_folder_id: str = None) -> None:
        """Download a file and save it to the specified path."""
        if not os.path.isabs(save_path):
            save_path = os.path.join("output", save_path)
            save_path = os.path.abspath(save_path)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        app_logger.info(f"Downloading file {file_id} to {save_path}")
        download_url = f"https://download.zoho.{self.client.domain}/v1/workdrive/download/{file_id}"
        response = self.client.request('GET', '', stream=True, override_url=download_url)
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: f.write(chunk)
        app_logger.info(f"Successfully downloaded file {file_id}")

    def _safe_download_name(self, name: Optional[str], fallback: str) -> str:
        """Return a filesystem-safe filename while keeping it readable."""
        candidate = (name or fallback or "unnamed").strip()
        candidate = _UNSAFE_FILENAME_CHARS.sub("_", candidate)
        candidate = candidate.rstrip(" .")
        if candidate in {"", ".", ".."}:
            return fallback or "unnamed"
        return candidate

    def _is_folder_item(self, item: Dict[str, Any]) -> bool:
        """Detect folder records across the shapes returned by WorkDrive APIs."""
        attrs = item.get("attributes") or {}
        return bool(
            attrs.get("is_folder")
            or item.get("type") == "folders"
            or attrs.get("type") == "folder"
            or attrs.get("resource_type") == "folder"
        )

    def _item_name(self, item: Dict[str, Any]) -> str:
        attrs = item.get("attributes") or {}
        return str(attrs.get("name") or item.get("name") or item.get("id") or "unnamed")

    def _next_available_download_path(self, path: Path, reserved_paths: set[Path]) -> Path:
        """Avoid duplicate source names in one run while keeping reruns idempotent."""
        if path not in reserved_paths:
            reserved_paths.add(path)
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if candidate not in reserved_paths:
                reserved_paths.add(candidate)
                return candidate
            counter += 1

    def download_folder(
        self,
        folder_id: str,
        destination: os.PathLike[str] | str,
        *,
        dry_run: bool = False,
    ) -> List[Path]:
        """Recursively download all files from a Zoho WorkDrive folder."""
        dest_path = Path(destination)
        if not dest_path.is_absolute():
            dest_path = Path("output") / dest_path
        root = dest_path.expanduser().resolve()
        downloaded: List[Path] = []
        reserved_paths: set[Path] = set()

        def walk(current_folder_id: str, current_local_dir: Path) -> None:
            app_logger.info(f"Listing WorkDrive folder {current_folder_id}")
            items = self.list_all_files(current_folder_id)
            current_local_dir.mkdir(parents=True, exist_ok=True)

            for item in items:
                item_id = str(item.get("id") or "")
                if not item_id:
                    app_logger.warning(f"Skipping WorkDrive item without an id: {item}")
                    continue

                safe_name = self._safe_download_name(self._item_name(item), item_id)
                local_path = current_local_dir / safe_name

                if self._is_folder_item(item):
                    walk(item_id, local_path)
                    continue

                target_path = self._next_available_download_path(local_path, reserved_paths)
                downloaded.append(target_path)
                if dry_run:
                    app_logger.info(f"Would download {item_id} -> {target_path}")
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                app_logger.info(f"Downloading {item_id} -> {target_path}")
                self.download(item_id, str(target_path), source_folder_id=current_folder_id)

        walk(folder_id, root)
        return downloaded

    def move(self, file_id: str, destination_folder_id: str) -> Dict[str, Any]:
        """Move a file to a new folder."""
        app_logger.info(f"Moving file {file_id} to folder {destination_folder_id}")
        payload = {"data": {"attributes": {"parent_id": destination_folder_id}, "type": "files"}}
        return self._action('PATCH', file_id, '', data=payload)

    def create_folder(self, name: str, parent_id: str) -> Dict[str, Any]:
        """Create a new folder in WorkDrive."""
        app_logger.info(f"Creating folder '{name}' in parent '{parent_id}'")
        payload = {"data": {"attributes": {"name": name, "parent_id": parent_id}, "type": "files"}}
        return self.client.request('POST', 'files', json=payload)

    def delete(self, resource_id: str) -> Dict[str, Any]:
        """Move a file or folder to the trash."""
        app_logger.info(f"Deleting (trashing) resource: {resource_id}")
        return self.client.request('DELETE', f"files/{resource_id}")

    def search(self, name: str, parent_id: Optional[str] = None, resource_type: Optional[str] = "folder") -> List[Dict[str, Any]]:
        """Search for files and folders using organization records search."""
        team_id = self.client.get_team_id()
        endpoint = f"organization/{team_id}/records"
        params = {"search[all]": name}
        if parent_id:
            params["filter[parentId]"] = parent_id
        if resource_type:
            params["filter[type]"] = resource_type

        res = self.client.request('GET', endpoint, params=params)
        return res.get('data', [])

    def upload(self, folder_id: str, file_path: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        """Upload a file to WorkDrive."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        name = file_name or os.path.basename(file_path)
        app_logger.info(f"Uploading file '{name}' to folder '{folder_id}'")
        import mimetypes
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type: content_type = 'application/octet-stream'
        with open(file_path, 'rb') as f:
            return self.client.request('POST', 'upload', params={"parent_id": folder_id}, files={'content': (name, f, content_type)})

    def get_base_name(self, name: str) -> str:
        """Extract base name from timestamped or numbered duplicates."""
        match = re.match(r"^(.*?)(?:\s+\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}:\d{3}|\s+\(\d+\))?$", name)
        return match.group(1).strip() if match else name

    def merge_folders(self, source_id: str, target_id: str, folder_name: str) -> None:
        """Recursively move contents from source folder to target folder."""
        app_logger.info(f"Merging contents of '{folder_name}' ({source_id}) -> ({target_id})")
        
        source_items = self.list_all_files(source_id)
        target_items = self.list_all_files(target_id)
        
        target_map = {item['attributes']['name']: item for item in target_items}
        
        for s_item in source_items:
            s_name = s_item['attributes']['name']
            s_id = s_item['id']
            is_folder = s_item['attributes'].get('is_folder', False)
            
            if s_name in target_map:
                t_item = target_map[s_name]
                if is_folder and t_item['attributes'].get('is_folder', False):
                    # Recursive merge for sub-folders
                    self.merge_folders(s_id, t_item['id'], s_name)
                else:
                    app_logger.warning(f"Collision for '{s_name}' in '{folder_name}': Skipping move.")
            else:
                try:
                    self.move(s_id, target_id)
                except Exception as e:
                    app_logger.error(f"Failed to move '{s_name}' during merge: {e}")

    def cleanup_duplicates(self, parent_id: str, recursive: bool = True) -> None:
        """Scan a folder for timestamped duplicates and merge them into the primary folders."""
        app_logger.info(f"Scanning for duplicates in folder: {parent_id} (recursive={recursive})")
        items = self.list_all_files(parent_id)
        
        groups = {}
        for item in items:
            name = item['attributes']['name']
            if not item['attributes'].get('is_folder', False):
                continue
            
            base_name = self.get_base_name(name)
            if base_name not in groups:
                groups[base_name] = []
            groups[base_name].append(item)

        for base_name, folder_list in groups.items():
            if len(folder_list) <= 1:
                continue
            
            app_logger.info(f"Found duplicates for base name: '{base_name}'")
            
            target_folder = None
            duplicates = []
            for f in folder_list:
                if f['attributes']['name'] == base_name:
                    target_folder = f
                else:
                    duplicates.append(f)
            
            if not target_folder:
                target_folder = duplicates.pop(0)
            
            for dup in duplicates:
                if recursive:
                    self.merge_folders(dup['id'], target_folder['id'], dup['attributes']['name'])
                else:
                    # Non-recursive: just move top-level items
                    dup_items = self.list_all_files(dup['id'])
                    for item in dup_items:
                        try:
                            self.move(item['id'], target_folder['id'])
                        except Exception as e:
                            app_logger.error(f"Failed to move '{item['attributes']['name']}': {e}")
                
                # Attempt to delete the empty duplicate folder
                try:
                    self.delete(dup['id'])
                    app_logger.info(f"Successfully deleted duplicate folder: {dup['attributes']['name']}")
                except Exception as e:
                    app_logger.error(f"Failed to delete empty duplicate folder {dup['attributes']['name']}: {e}")
