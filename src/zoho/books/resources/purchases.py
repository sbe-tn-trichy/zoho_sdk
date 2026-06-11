from collections import defaultdict
from typing import Any, Dict, Iterable, Optional, List
from ..base import BaseResource
from ..mixins import StatusMixin, ApprovalMixin, CreditsMixin

class Bills(BaseResource, StatusMixin, ApprovalMixin, CreditsMixin):
    # Top-level requirements
    required_fields = ["bill_number", "vendor_id", "date", "line_items"]
    
    # Top-level defaults
    defaults = {
        "adjustment": 0,
        "adjustment_description": "Adjustment",
        "is_item_level_tax_calc": False,
        "is_draft": True,
        "discount": 0,
        "discount_type": "entity_level",
        "gst_treatment": "business_gst",
        "entity_type": "bill"
    }

    # Line item requirements
    line_item_required_fields = [
        "item_id", "account_id", "rate", "quantity", 
        "tax_id", "name", "hsn_or_sac"
    ]

    # Line item defaults
    line_item_defaults = {
        "discount": 0,
        "itc_eligibility": "eligible",
        "unit": "NOS"
    }

    def __init__(self, client: Any):
        super().__init__(client, 'bills')

    @staticmethod
    def normalize_bill_number(bill_number: Any) -> str:
        """Normalize bill numbers for duplicate grouping."""
        if bill_number is None:
            return ""
        return str(bill_number).strip()

    @classmethod
    def find_duplicate_groups(cls, bills: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group bill records with repeated non-blank bill numbers."""
        groups = defaultdict(list)

        for bill in bills:
            bill_number = cls.normalize_bill_number(bill.get("bill_number"))
            if bill_number:
                groups[bill_number].append(bill)

        return {
            bill_number: bill_group
            for bill_number, bill_group in groups.items()
            if len(bill_group) > 1
        }

    def list_duplicate_bill_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch all bills and return groups with duplicate bill numbers."""
        bills = self.list_all(resource_key="bills")
        return self.find_duplicate_groups(bills)

    def update(self, bill_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Update an existing bill.
        
        Note: Zoho Books typically requires the full payload for updates.
        Missing fields may be reset to defaults or cleared.
        """
        payload = self._prepare_payload(data)
        return self.client.request('PUT', f"{self.endpoint}/{bill_id}", json=payload, params=params, files=files)

    def add_attachment(self, bill_id: str, file_content: Any, filename: str) -> Dict[str, Any]:
        """
        Attach a file to an existing bill.
        """
        files = {
            'attachment': (filename, file_content)
        }
        return self.client.request('POST', f"{self.endpoint}/{bill_id}/attachment", files=files)

class PurchaseOrders(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'purchaseorders')

    def mark_as_billed(self, po_id: str) -> Dict[str, Any]:
        return self._action('POST', po_id, 'status/billed')

    def mark_as_cancelled(self, po_id: str) -> Dict[str, Any]:
        return self._action('POST', po_id, 'status/cancelled')

class VendorPayments(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'vendorpayments')
