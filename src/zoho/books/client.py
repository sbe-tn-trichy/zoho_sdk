import logging
import os
from typing import Any, Dict, Optional
from zoho.base_client import BaseZohoClient
from .resources.contacts import Contacts, Organizations, ChartOfAccounts, Vendors
from .resources.sales import Invoices, Estimates, SalesOrders, CreditNotes, SalesReturns, CustomerPayments
from .resources.purchases import Bills, PurchaseOrders, VendorPayments
from .resources.banking import BankAccounts, BankTransactions, Journals
from .resources.projects import Projects, Tasks, TimeEntries
from .resources.inventory import Items
from .resources.gst import GST
from .resources.customer_validator import CustomerValidator

class ZohoBooksAPI(BaseZohoClient):
    """
    Main Zoho Books API Client linking all modules together.
    """
    def __init__(
        self,
        access_token: str,
        organization_id: str,
        domain: str = "com",
        on_request_completed: Optional[Any] = None,
        token_refresh_callback: Optional[Any] = None
    ):
        """
        Initialize the Zoho Books API client.
        """
        if not organization_id:
            raise ValueError("organization_id is required.")
            
        base_url = f"https://www.zohoapis.{domain}/books/v3"
        super().__init__(
            access_token=access_token,
            domain=domain,
            base_url=base_url,
            service_name="books",
            token_refresh_callback=token_refresh_callback,
            on_request_completed=on_request_completed,
            default_timeout=30
        )
        self.organization_id = organization_id
        
        # Initialize modules
        self.organizations = Organizations(self)
        self.contacts = Contacts(self)
        self.vendors = Vendors(self)
        self.invoices = Invoices(self)
        self.estimates = Estimates(self)
        self.sales_orders = SalesOrders(self)
        self.credit_notes = CreditNotes(self)
        self.sales_returns = SalesReturns(self)
        self.customer_payments = CustomerPayments(self)
        self.bills = Bills(self)
        self.purchase_orders = PurchaseOrders(self)
        self.vendor_payments = VendorPayments(self)
        self.bank_accounts = BankAccounts(self)
        self.bank_transactions = BankTransactions(self)
        self.journals = Journals(self)
        self.chart_of_accounts = ChartOfAccounts(self)
        self.projects = Projects(self)
        self.tasks = Tasks(self)
        self.time_entries = TimeEntries(self)
        self.items = Items(self)
        self.gst = GST(self)
        self.customer_validator = CustomerValidator(self)

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Internal HTTP request handler with logging.
        """
        params = params or {}
        if 'organization_id' not in params:
            params['organization_id'] = self.organization_id
            
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            params=params,
            files=files
        )
