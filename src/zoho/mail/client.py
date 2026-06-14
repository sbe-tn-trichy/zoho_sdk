import logging
import os
from typing import Any, Dict, Optional
from zoho.base_client import BaseZohoClient
from .resources.accounts import Accounts
from .resources.folders import Folders
from .resources.messages import Messages

class ZohoMailAPI(BaseZohoClient):
    """
    Main Zoho Mail API Client.
    """
    def __init__(self, access_token: str, domain: str = "com", token_refresh_callback: Optional[Any] = None):
        """
        Initialize the Zoho Mail API client.
        """
        base_url = f"https://mail.zoho.{domain}/api"
        super().__init__(
            access_token=access_token,
            domain=domain,
            base_url=base_url,
            service_name="mail",
            token_refresh_callback=token_refresh_callback
        )
        # Global resources
        self.accounts = Accounts(self)

    def account(self, account_id: str):
        """
        Returns a helper object to access account-specific resources.
        """
        class AccountScope:
            def __init__(self, client, acc_id):
                self.folders = Folders(client, acc_id)
                self.messages = Messages(client, acc_id)
        
        return AccountScope(self, account_id)

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        stream: bool = False
    ) -> Any:
        """
        Internal HTTP request handler with logging.
        """
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            params=params,
            files=files,
            stream=stream
        )
