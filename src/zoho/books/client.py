import requests
import logging
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional
from .exceptions import ZohoBooksError
from .resources.contacts import Contacts, Organizations, ChartOfAccounts
from .resources.sales import Invoices, Estimates, SalesOrders, CreditNotes, SalesReturns, CustomerPayments
from .resources.purchases import Bills, PurchaseOrders, VendorPayments
from .resources.banking import BankAccounts, BankTransactions, Journals
from .resources.projects import Projects, Tasks, TimeEntries
from .resources.inventory import Items
from .resources.gst import GST
from .resources.customer_validator import CustomerValidator

# Configure logger without external project dependencies
logger = logging.getLogger("zoho_books")
logger.setLevel(logging.INFO)
if not logger.handlers:
    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
    is_testing = "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"
    log_dir = os.path.join(project_root, "tests" if is_testing else "", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "zoho_books_api.log"), encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass

class ZohoBooksAPI:
    """
    Main Zoho Books API Client linking all modules together.
    """
    def __init__(self, access_token: str, organization_id: str, domain: str = "com", on_request_completed: Optional[Any] = None, token_refresh_callback: Optional[Any] = None):
        """
        Initialize the Zoho Books API client.
        """
        self.access_token = access_token
        self.organization_id = organization_id
        if not self.organization_id:
            logger.error("organization_id is required.")
            raise ValueError("organization_id is required.")
        
        self.base_url = f"https://www.zohoapis.{domain}/books/v3"
        self.on_request_completed = on_request_completed
        self.token_refresh_callback = token_refresh_callback

        
        # Initialize modules
        self.organizations = Organizations(self)
        self.contacts = Contacts(self)
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
            logger.warning("Books request returned 401; calling token refresh callback and retrying once.")
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
            return response.json()
        except requests.exceptions.HTTPError as e:
            raise ZohoBooksError(f"HTTP Error: {response.status_code} - {response.text}") from e
