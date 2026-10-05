"""Higher-level helper functions for WorkDrive uploads and Books attachments."""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from zoho.downloads import write_response_to_file
from zoho.security import resolve_output_path

logger = logging.getLogger("zoho.helpers.files")


def download_books_document(
    books_client: Any, resource_name: str, resource_id: str, document_id: str,
    save_path: str,
) -> str:
    """Download a specific Books document; relative paths are confined to output/."""
    if not re.fullmatch(r'[a-z][a-z0-9]*', resource_name):
        raise ValueError('Invalid Books resource name')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (resource_id, document_id)):
        raise ValueError('Invalid Books resource/document ID')
    destination = resolve_output_path(save_path)
    response = books_client.request(
        'GET', f'{resource_name}/{resource_id}/documents/{document_id}', stream=True,
    )
    return write_response_to_file(response, destination)


def workdrive_upload_file(
    wd_client: Any,
    folder_id: str,
    file_path: str,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a local file to a Zoho WorkDrive folder."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    upload_name = file_name or path.name
    logger.info(f"Uploading '{upload_name}' to WorkDrive folder '{folder_id}'")
    return wd_client.files.upload(folder_id=folder_id, file_path=str(path), file_name=upload_name)


def attach_file_to_books_resource(
    books_client: Any,
    resource_name: str,
    resource_id: str,
    file_path: str,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a local file to a Zoho Books transaction (e.g., invoices, salesorders, bills)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    name = file_name or path.name
    content_type, _ = mimetypes.guess_type(str(path))
    if not content_type:
        content_type = "application/octet-stream"

    endpoint = f"{resource_name.strip('/')}/{resource_id}/attachment"
    logger.info(f"Attaching '{name}' to Books resource {endpoint}")

    with open(path, "rb") as f:
        files = {"attachment": (name, f, content_type)}
        return books_client.request("POST", endpoint, files=files)


def workdrive_upload_and_attach(
    wd_client: Any,
    books_client: Any,
    folder_id: str,
    file_path: str,
    resource_name: str,
    resource_id: str,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a file to WorkDrive and attach it to a Books resource in a single composite call."""
    wd_res = workdrive_upload_file(wd_client, folder_id, file_path, file_name=file_name)
    books_res = attach_file_to_books_resource(
        books_client,
        resource_name,
        resource_id,
        file_path,
        file_name=file_name,
    )
    return {
        "workdrive": wd_res,
        "books_attachment": books_res,
    }
