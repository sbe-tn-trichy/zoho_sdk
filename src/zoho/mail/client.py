import requests
import logging
import os
import json as json_tool
from typing import Any, Dict, Optional
from .exceptions import ZohoMailError
from .resources.accounts import Accounts
from .resources.folders import Folders
from .resources.messages import Messages

# Configure logger without external project imports
logger = logging.getLogger("zoho_mail")
logger.setLevel(logging.INFO)
if not logger.handlers:
    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
    is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
    log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "zoho_mail_api.log"))
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass

class ZohoMailAPI:
    """
    Main Zoho Mail API Client.
    """
    def __init__(self, access_token: str, domain: str = "com"):
        """
        Initialize the Zoho Mail API client.
        """
        self.access_token = access_token
        self.base_url = f"https://mail.zoho.{domain}/api"

        
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

    def request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, stream: bool = False) -> Any:
        """
        Internal HTTP request handler with logging.
        """
        url = f"{self.base_url}/{endpoint}"
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}"
        }
        
        if not files:
            headers["Content-Type"] = "application/json"

        # Log Request
        log_msg = f"Request: {method} {url} | Params: {params}"
        if json:
            log_msg += f" | Payload: {json}"
        logger.info(log_msg)

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json,
            files=files,
            stream=stream
        )
        
        # Log Response
        logger.info(f"Response: {response.status_code}")
        
        try:
            response.raise_for_status()
            
            if stream:
                return response

            # Zoho Mail sometimes returns empty response for DELETE or some updates
            if response.status_code == 204 or not response.text:
                return {}
            return response.json()
        except requests.exceptions.HTTPError as e:
            # Log full request details on failure
            error_details = {
                "method": method,
                "url": url,
                "headers": {k: v for k, v in headers.items() if k != "Authorization"},
                "params": params,
                "status_code": response.status_code,
                "response_text": response.text
            }
            logger.error(f"Zoho Mail Request Failed: {json_tool.dumps(error_details)}")
            raise ZohoMailError(f"HTTP Error: {response.status_code} - {response.text}") from e
