import logging
import os
from typing import Any, Dict, Optional
from zoho.base_client import BaseZohoClient
from .exceptions import ZohoWorkdriveError
from .resources.files import Files

class ZohoWorkdriveAPI(BaseZohoClient):
    """
    Main Zoho Workdrive API Client.
    """
    def __init__(
        self,
        access_token: str,
        domain: str = "in",
        team_id: Optional[str] = None,
        token_refresh_callback: Optional[Any] = None
    ):
        """
        Initialize the Zoho Workdrive API client.
        """
        base_url = f"https://www.zohoapis.{domain or 'in'}/workdrive/api/v1"
        super().__init__(
            access_token=access_token,
            domain=domain or "in",
            base_url=base_url,
            service_name="wd",
            token_refresh_callback=token_refresh_callback
        )
        self._team_id = team_id
        self.files = Files(self)

    def get_team_id(self) -> str:
        """Fetch the team ID (organization ID) for the current user."""
        app_logger = logging.getLogger("zoho.wd.app")
        if not self._team_id:
            app_logger.info("WORKDRIVE_TEAM_ID not provided, fetching from API...")
            res = self.request('GET', 'users/me')
            attrs = res.get('data', {}).get('attributes', {})
            # Try both team_id and preferred_team_id
            self._team_id = attrs.get('team_id') or attrs.get('preferred_team_id')
            
            if not self._team_id:
                app_logger.error("Could not determine WorkDrive Team ID")
                raise ZohoWorkdriveError("Could not determine WorkDrive Team ID")
                
        return self._team_id

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        override_url: Optional[str] = None,
        files: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Internal HTTP request handler.
        """
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            params=params,
            stream=stream,
            override_url=override_url,
            files=files
        )
