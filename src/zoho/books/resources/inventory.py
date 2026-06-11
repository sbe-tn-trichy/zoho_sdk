from typing import Any, Dict
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class Items(BaseResource, ActiveInactiveMixin):
    # Extensive list of required fields based on sample item JSON
    required_fields = [
        "name", "sku", "rate", "account_id", 
        "purchase_rate", "purchase_account_id", "inventory_account_id",
        "is_taxable", "product_type", "hsn_or_sac", "item_tax_preferences",
        "unit", "inventory_valuation_method", "can_be_sold", 
        "can_be_purchased", "track_inventory"
    ]

    # Smart defaults to simplify creation
    defaults = {
        "rate": 0,
        "purchase_rate": 0,
        "is_taxable": True,
        "product_type": "goods",
        "unit": "NOS",
        "inventory_valuation_method": "fifo",
        "can_be_sold": True,
        "can_be_purchased": True,
        "track_inventory": True,
        "is_returnable": True,
        "is_storage_location_enabled": True
    }

    def __init__(self, client: Any):
        super().__init__(client, 'items')

    def list_by_purchase_account(self, account_id: str, status: str = "all") -> list:
        """
        Fetch all items associated with a specific purchase account.
        
        Args:
            account_id (str): The Zoho Books purchase account ID.
            status (str): Filter by status ('all', 'active', 'inactive'). Defaults to 'all'.
        
        Returns:
            list: List of item records.
        """
        filter_map = {
            "all": "Status.All",
            "active": "Status.Active",
            "inactive": "Status.Inactive"
        }
        params = {
            "purchase_account_id": account_id,
            "filter_by": filter_map.get(status.lower(), "Status.All")
        }
        return self.list_all(params=params)
