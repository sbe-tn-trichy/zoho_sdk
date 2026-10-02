import os
from typing import Any, Dict, Optional
from ..base import BaseResource
from ..mixins import StatusMixin, EmailMixin, ApprovalMixin, CreditsMixin

class Invoices(BaseResource, StatusMixin, EmailMixin, ApprovalMixin, CreditsMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'invoices')

    def apply_credits(self, invoice_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', invoice_id, 'credits', data=data)

class Estimates(BaseResource, StatusMixin, EmailMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'estimates')

    def mark_as_accepted(self, estimate_id: str) -> Dict[str, Any]:
        return self._action('POST', estimate_id, 'status/accepted')

    def mark_as_declined(self, estimate_id: str) -> Dict[str, Any]:
        return self._action('POST', estimate_id, 'status/declined')

class SalesOrders(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'salesorders')

    def add_attachment(self, sales_order_id: str, file_path: str) -> Dict[str, Any]:
        """Attach a local file to a sales order."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as handle:
            files = {"attachment": (filename, handle, "application/pdf")}
            return self.client.request(
                "POST",
                f"salesorders/{sales_order_id}/attachment",
                files=files,
            )

class CreditNotes(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'creditnotes')

class VendorCredits(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'vendorcredits')

    def add_attachment(self, vendor_credit_id: str, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as handle:
            files = {"attachment": (filename, handle, "application/pdf")}
            return self.client.request(
                "POST",
                f"vendorcredits/{vendor_credit_id}/attachment",
                files=files,
            )

class SalesReturns(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'salesreturns')

class CustomerPayments(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'customerpayments')
        
    def refund(self, payment_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', payment_id, 'refunds', data=data)

    def update_with_number_series(self, payment_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a payment via multipart form while preserving the chosen number series."""
        import json

        if not payment_id or not data.get("location_id"):
            raise ValueError("Payment ID and destination location are required")
        if not data.get("payment_number_prefix") or not data.get("payment_number_suffix"):
            raise ValueError("Payment number prefix and suffix are required")
        return self.client.request(
            "PUT", f"{self.endpoint}/{payment_id}",
            files={"JSONString": (None, json.dumps(data)),
                   "ignore_auto_number_generation": (None, "true")},
        )
