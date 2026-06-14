from ..base import BaseResource
from typing import Any, Dict, Optional, List
import os

class Messages(BaseResource):
    def __init__(self, client, account_id: str):
        super().__init__(client, f"accounts/{account_id}/messages")
        self.account_id = account_id

    def list(self, folder_id: Optional[str] = None, page: int = 1, limit: int = 50, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        List messages summary.
        :param folder_id: Optional folder ID to filter messages.
        :param page: Page number (default: 1).
        :param limit: Number of messages per page (default: 50).
        :param params: Additional query parameters.
        """
        query_params = {
            "start": (page - 1) * limit + 1,
            "limit": limit
        }
        if folder_id:
            query_params["folderId"] = folder_id
        
        if params:
            query_params.update(params)
            
        return self.client.request('GET', f"{self.endpoint}/view", params=query_params)

    def get_content(self, message_id: str) -> Dict[str, Any]:
        """Get full message content."""
        return self.client.request('GET', f"{self.endpoint}/{message_id}/content")

    def send(self, from_address: str, to_address: str, subject: str, content: str, **kwargs) -> Dict[str, Any]:
        """Send an email."""
        data = {
            "fromAddress": from_address,
            "toAddress": to_address,
            "subject": subject,
            "content": content,
            "action": "send"
        }
        data.update(kwargs)
        return self.create(data)

    def save_draft(self, from_address: str, to_address: str, subject: str, content: str, **kwargs) -> Dict[str, Any]:
        """Save a draft email."""
        data = {
            "fromAddress": from_address,
            "toAddress": to_address,
            "subject": subject,
            "content": content,
            "action": "save"
        }
        data.update(kwargs)
        return self.create(data)

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Mark message as read."""
        return self.update(message_id, {"status": "read"})

    def mark_as_unread(self, message_id: str) -> Dict[str, Any]:
        """Mark message as unread."""
        return self.update(message_id, {"status": "unread"})

    def get_attachments_info(self, folder_id: str, message_id: str) -> Dict[str, Any]:
        """Get attachment information for a message."""
        # The endpoint for listing attachments requires the folder ID and message ID
        endpoint = f"accounts/{self.account_id}/folders/{folder_id}/messages/{message_id}/attachmentinfo"
        return self.client.request('GET', endpoint)

    def get_attachment_content(self, folder_id: str, message_id: str, attachment_id: str) -> bytes:
        """Get attachment content."""
        endpoint = f"accounts/{self.account_id}/folders/{folder_id}/messages/{message_id}/attachments/{attachment_id}"
        response = self.client.request('GET', endpoint, stream=True)
        return response.content

    def download_attachment(self, folder_id: str, message_id: str, attachment_id: str, download_path: str) -> str:
        """
        Download attachment and save to specified path.
        Returns the final file path (handles duplicates if needed, though here it just writes).
        """
        if not os.path.isabs(download_path):
            download_path = os.path.join("output", download_path)
        content = self.get_attachment_content(folder_id, message_id, attachment_id)
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        with open(download_path, "wb") as f:
            f.write(content)
        return download_path

    def list_iter(self, folder_id: Optional[str] = None, start: int = 1, limit: int = 50):
        """
        Iterator for messages in a folder.
        """
        current_start = start
        while True:
            # Calculate page for the existing list method
            page = ((current_start - 1) // limit) + 1
            response = self.list(folder_id=folder_id, page=page, limit=limit)
            data = response.get('data', [])
            if not data:
                break

            for msg in data:
                yield msg

            if len(data) < limit:
                break
            current_start += limit

    def message_has_attachment(self, message: Dict[str, Any]) -> bool:
        """Return True when a Zoho message summary indicates attachments."""
        return str(message.get('hasAttachment', '')).lower() in ('1', 'true', 'yes')

    def extract_attachments(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize Zoho attachment metadata response shapes."""
        data = response.get('data', [])
        if isinstance(data, dict):
            attachments = data.get('attachments', [])
        elif isinstance(data, list):
            attachments = data
        else:
            return []

        return [att for att in attachments if isinstance(att, dict)]

    def resolve_download_path(self, download_dir: str, attachment_name: str, sequence_index: Optional[int] = None) -> str:
        """Return a collision-safe path for an attachment in the target directory."""
        base_name, extension = os.path.splitext(attachment_name)
        if sequence_index:
            attachment_name = f"{base_name}_{sequence_index}{extension}"
            base_name, extension = os.path.splitext(attachment_name)

        target_path = os.path.join(download_dir, attachment_name)
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(download_dir, f"{base_name}_{counter}{extension}")
            counter += 1
        return target_path

    def download_folder_attachments(self, folder_id: str, download_dir: str, filename: Optional[str] = None) -> List[str]:
        """
        Downloads all attachments from all messages in a specific folder.
        
        :param folder_id: The ID of the folder to process.
        :param download_dir: The local directory where attachments should be saved.
        :param filename: Optional local filename to use instead of Zoho attachment names.
        :return: A list of absolute paths to the downloaded files.
        """
        if not os.path.isabs(download_dir):
            download_dir = os.path.join("output", download_dir)
        os.makedirs(download_dir, exist_ok=True)
        downloaded_paths = []
        override_index = 0

        for msg in self.list_iter(folder_id=folder_id):
            if not self.message_has_attachment(msg):
                continue

            msg_id = msg.get('messageId')
            if not msg_id:
                continue

            att_info_resp = self.get_attachments_info(folder_id, msg_id)
            for att in self.extract_attachments(att_info_resp):
                att_name = att.get('attachmentName')
                att_id = att.get('attachmentId')
                
                if not att_id or (not att_name and not filename):
                    continue
                
                sequence_index = None
                target_name = att_name
                if filename:
                    target_name = filename
                    sequence_index = override_index or None
                    override_index += 1

                target_path = self.resolve_download_path(download_dir, target_name, sequence_index=sequence_index)
                final_path = self.download_attachment(folder_id, msg_id, att_id, target_path)
                downloaded_paths.append(os.path.abspath(final_path))
        
        return downloaded_paths
