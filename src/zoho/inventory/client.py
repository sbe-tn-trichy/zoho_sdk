import logging
import os
from typing import Any, Dict, Optional
from zoho.base_client import BaseZohoClient
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

class ZohoInventoryAPI(BaseZohoClient):
    """
    Main Zoho Inventory API Client linking all modules together.
    """
    def __init__(
        self,
        access_token: str,
        organization_id: str,
        domain: str = "com",
        on_request_completed: Optional[Any] = None,
        token_refresh_callback: Optional[Any] = None
    ):
        if not organization_id:
            raise ValueError("organization_id is required.")
            
        base_url = f"https://www.zohoapis.{domain}/inventory/v1"
        super().__init__(
            access_token=access_token,
            domain=domain,
            base_url=base_url,
            service_name="inventory",
            token_refresh_callback=token_refresh_callback,
            on_request_completed=on_request_completed,
            default_timeout=30
        )
        self.organization_id = organization_id

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

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        override_url: Optional[str] = None,
        is_mutation: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        """
        Internal HTTP request handler with logging.
        """
        params = dict(params or {})
        if 'organization_id' not in params:
            params['organization_id'] = self.organization_id
            
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            data=data,
            params=params,
            headers=headers,
            files=files,
            stream=stream,
            override_url=override_url,
            is_mutation=is_mutation,
            timeout=timeout,
        )
