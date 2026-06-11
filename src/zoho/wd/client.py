import requests
import logging
import json as json_lib
import os
from typing import Any, Dict, Optional
from .exceptions import ZohoWorkdriveError
from .resources.files import Files

# Configure API logger without external project imports
api_logger = logging.getLogger("zoho.wd.api")
api_logger.setLevel(logging.INFO)
if not api_logger.handlers:
    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
    is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
    log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        api_handler = logging.FileHandler(os.path.join(log_dir, "zoho_wd_api.log"))
        api_handler.setFormatter(logging.Formatter('%(asctime)s - [API] %(levelname)s - %(message)s'))
        api_logger.addHandler(api_handler)
    except Exception:
        pass

# Configure App logger without external project imports
app_logger = logging.getLogger("zoho.wd.app")
app_logger.setLevel(logging.INFO)
if not app_logger.handlers:
    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
    is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
    log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        app_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
        app_handler.setFormatter(logging.Formatter('%(asctime)s - [APP] [ZOHO_WD] %(levelname)s - [%(funcName)s] - %(message)s'))
        app_logger.addHandler(app_handler)
    except Exception:
        pass

class ZohoWorkdriveAPI:
    """
    Main Zoho Workdrive API Client.
    """
    def __init__(self, access_token: str, domain: str = "in", team_id: Optional[str] = None, token_refresh_callback: Optional[Any] = None):
        """
        Initialize the Zoho Workdrive API client.
        """
        self.access_token = access_token
        self.domain = domain or "in"
        self.base_url = f"https://www.zohoapis.{self.domain}/workdrive/api/v1"

        # Initialize modules
        self.files = Files(self)
        self._team_id = team_id
        self.token_refresh_callback = token_refresh_callback

    def get_team_id(self) -> str:
        """Fetch the team ID (organization ID) for the current user."""
        if not self._team_id:
            # Fallback to API if not set
            app_logger.info("WORKDRIVE_TEAM_ID not provided, fetching from API...")
            res = self.request('GET', 'users/me')
            attrs = res.get('data', {}).get('attributes', {})
            # Try both team_id and preferred_team_id
            self._team_id = attrs.get('team_id') or attrs.get('preferred_team_id')
            
            if not self._team_id:
                app_logger.error("Could not determine WorkDrive Team ID")
                raise ZohoWorkdriveError("Could not determine WorkDrive Team ID")
                
        return self._team_id

    def request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, stream: bool = False, override_url: Optional[str] = None, files: Optional[Dict[str, Any]] = None) -> Any:
        """
        Internal HTTP request handler.
        """
        url = override_url if override_url else f"{self.base_url}/{endpoint}"
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}"
        }
        if not files:
            headers["Accept"] = "application/vnd.api+json"
        
        # Log Request
        from urllib.parse import urlparse
        path = urlparse(url).path
        api_logger.info(f"Request: {method} {path}")

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json,
            stream=stream,
            files=files
        )
        if response.status_code == 401 and self.token_refresh_callback:
            api_logger.warning("WorkDrive request returned 401; calling token refresh callback and retrying once.")
            self.access_token = self.token_refresh_callback()
            headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                stream=stream,
                files=files
            )
        
        # Log response ONLY if stream is false, otherwise we'd consume the stream
        if stream:
            # We don't read the response text for streaming, just log status
            api_logger.info(f"Response: {response.status_code}")
            if response.status_code >= 400:
                app_logger.error(f"Stream error: HTTP {response.status_code}")
                response.raise_for_status()
            return response
        else:
            api_logger.info(f"Response: {response.status_code}")
            
            try:
                response.raise_for_status()
                if response.content:
                    return response.json()
                return {}
            except requests.exceptions.HTTPError as e:
                error_msg = response.text
                raise ZohoWorkdriveError(f"HTTP Error: {response.status_code} - {error_msg}") from e
