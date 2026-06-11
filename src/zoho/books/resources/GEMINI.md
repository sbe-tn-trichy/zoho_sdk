# Folder Index: `zoho/books/resources`

Zoho Books Resource modules mapping to specific API endpoints.

## Files and Available Classes/Methods

### [banking.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/banking.py)
- **[BankAccounts](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/banking.py#L5)** (inherits `BaseResource`, `ActiveInactiveMixin`)
- **[BankTransactions](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/banking.py#L9)** (inherits `BaseResource`)
  - `match(self, transaction_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
  - `categorize_as_expense(self, transaction_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
- **[Journals](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/banking.py#L19)** (inherits `BaseResource`)
  - `publish(self, journal_id: str) -> Dict[str, Any]`

### [contacts.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/contacts.py)
- **[Contacts](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/contacts.py#L5)** (inherits `BaseResource`, `ActiveInactiveMixin`)
  - `enable_portal(self, contact_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
  - `email_statement(self, contact_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
- **[Organizations](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/contacts.py#L15)** (inherits `BaseResource`)
- **[ChartOfAccounts](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/contacts.py#L19)** (inherits `BaseResource`, `ActiveInactiveMixin`)

### [customer_validator.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/customer_validator.py)
- **[CustomerValidator](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/customer_validator.py#L9)** (inherits `BaseResource`)
  - `check_proper_casing(self, text: str) -> List[str]`
  - `check_punctuation_anomalies(self, text: str) -> List[str]`
  - `check_phone_isd(self, number: str) -> Optional[str]`
  - `check_geographic_name(self, contact: Dict[str, Any]) -> Optional[str]`
  - `check_custom_fields(self, contact: Dict[str, Any]) -> List[str]`
  - `validate_customer_data(self, limit: Optional[int] = None) -> Dict[str, Any]`

### [gst.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/gst.py)
- **[GST](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/gst.py#L31)** (inherits `BaseResource`)
  - `get_month_date_range(self, month_str: str) -> Tuple[str, str]`
  - `validate_gst_data(self, month_str: str) -> Dict[str, Any]`

### [inventory.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/inventory.py)
- **[Items](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/inventory.py#L5)** (inherits `BaseResource`, `ActiveInactiveMixin`)
  - `list_by_purchase_account(self, account_id: str, status: str = "all") -> list`

### [projects.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/projects.py)
- **[Projects](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/projects.py#L5)** (inherits `BaseResource`, `ActiveInactiveMixin`)
  - `clone(self, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
- **[Tasks](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/projects.py#L12)** (inherits `BaseResource`)
- **[TimeEntries](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/projects.py#L16)** (inherits `BaseResource`)
  - `start_timer(self, time_entry_id: str) -> Dict[str, Any]`
  - `stop_timer(self) -> Dict[str, Any]`

### [purchases.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/purchases.py)
- **[Bills](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/purchases.py#L6)** (inherits `BaseResource`, `StatusMixin`, `ApprovalMixin`, `CreditsMixin`)
  - `normalize_bill_number(bill_number: Any) -> str` (Static)
  - `find_duplicate_groups(bills: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]` (Classmethod)
  - `list_duplicate_bill_groups(self) -> Dict[str, List[Dict[str, Any]]]`
  - `add_attachment(self, bill_id: str, file_content: Any, filename: str) -> Dict[str, Any]`
- **[PurchaseOrders](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/purchases.py#L85)** (inherits `BaseResource`, `StatusMixin`)
  - `mark_as_billed(self, po_id: str) -> Dict[str, Any]`
  - `mark_as_cancelled(self, po_id: str) -> Dict[str, Any]`
- **[VendorPayments](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/purchases.py#L95)** (inherits `BaseResource`)

### [sales.py](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py)
- **[Invoices](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L5)** (inherits `BaseResource`, `StatusMixin`, `EmailMixin`, `ApprovalMixin`, `CreditsMixin`)
  - `apply_credits(self, invoice_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
- **[Estimates](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L12)** (inherits `BaseResource`, `StatusMixin`, `EmailMixin`)
  - `mark_as_accepted(self, estimate_id: str) -> Dict[str, Any]`
  - `mark_as_declined(self, estimate_id: str) -> Dict[str, Any]`
- **[SalesOrders](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L22)** (inherits `BaseResource`, `StatusMixin`)
  - `create_from_yaml(self, yaml_str: str, customer_id: str = "1094368000001317103", create_missing_items: bool = False) -> Dict[str, Any]`
- **[CreditNotes](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L184)** (inherits `BaseResource`, `StatusMixin`)
- **[SalesReturns](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L188)** (inherits `BaseResource`, `StatusMixin`)
- **[CustomerPayments](file:///d:/workplace/zoho_sdk/src/zoho/books/resources/sales.py#L192)** (inherits `BaseResource`)
  - `refund(self, payment_id: str, data: Dict[str, Any]) -> Dict[str, Any]`
