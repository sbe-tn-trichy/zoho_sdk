import requests
import logging
import os
from typing import Any, Dict, Optional
from .exceptions import ZohoInventoryError
from .resources.items import Items
from .resources.move_orders import MoveOrders
from .resources.transfer_orders import TransferOrders
from .resources.inventory_adjustments import InventoryAdjustments
from .resources.packages import Packages
from .resources.shipments import Shipments
from .resources.picklists import Picklists
from .resources.bins import Bins
from .resources.batches import Batches
from .resources.item_groups import ItemGroups

logger = logging.getLogger("zoho_inventory")
logger.setLevel(logging.INFO)
if not logger.handlers:
    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
    is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
    log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "zoho_inventory_api.log"), encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass

class ZohoInventoryAPI:
    """
    Main Zoho Inventory API Client linking all modules together.
    """
    def __init__(self, access_token: str, organization_id: str, domain: str = "com", on_request_completed: Optional[Any] = None, token_refresh_callback: Optional[Any] = None):
        self.access_token = access_token
        self.organization_id = organization_id
        if not self.organization_id:
            logger.error("organization_id is required.")
            raise ValueError("organization_id is required.")
        
        self.base_url = f"https://www.zohoapis.{domain}/inventory/v1"
        self.on_request_completed = on_request_completed
        self.token_refresh_callback = token_refresh_callback

        # Initialize sub-resources
        self.items = Items(self)
        self.move_orders = MoveOrders(self)
        self.transfer_orders = TransferOrders(self)
        self.inventory_adjustments = InventoryAdjustments(self)
        self.packages = Packages(self)
        self.shipments = Shipments(self)
        self.picklists = Picklists(self)
        self.bins = Bins(self)
        self.batches = Batches(self)
        self.item_groups = ItemGroups(self)

    def request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Internal HTTP request handler with logging.
        """
        url = f"{self.base_url}/{endpoint}"
        
        params = params or {}
        if 'organization_id' not in params:
            params['organization_id'] = self.organization_id
            
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
            timeout=30
        )
        if response.status_code == 401 and self.token_refresh_callback:
            logger.warning("Inventory request returned 401; calling token refresh callback and retrying once.")
            self.access_token = self.token_refresh_callback()
            headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                files=files,
                timeout=30
            )
        
        # Log Response
        logger.info(f"Response: {response.status_code}")
        
        # Log to callback if configured
        if self.on_request_completed:
            try:
                self.on_request_completed(method, endpoint, json, response.status_code, response.text)
            except Exception as e:
                logger.error(f"Callback on_request_completed failed: {e}")
        
        try:
            response.raise_for_status()
            # Handle empty response content
            if response.status_code == 204 or not response.text:
                return {}
            return response.json()
        except requests.exceptions.HTTPError as e:
            raise ZohoInventoryError(f"HTTP Error: {response.status_code} - {response.text}") from e
