"""Higher-level overlay helpers and composite operations for Zoho SDK."""

from .accounts import (
    fetch_bank_accounts_map,
    find_bank_account_by_name,
)
from .contacts import (
    fetch_active_customers_map,
    find_contact_by_gstin,
    find_contact_by_name,
)
from .custom_fields import (
    ensure_books_custom_fields,
    extract_custom_fields_dict,
    get_custom_field_value,
)
from .dates import (
    get_month_range,
    get_previous_month_range,
    parse_date,
)
from .files import (
    attach_file_to_books_resource,
    workdrive_upload_and_attach,
    workdrive_upload_file,
)
from .gst import (
    GSTIN_PATTERN,
    group_contacts_by_gstin,
    is_valid_gstin,
    normalize_gstin,
)
from .items import (
    fetch_items_lookup,
    find_item_by_sku_or_name,
)
from .transactions import (
    find_transaction_by_number,
    unwrap_record,
)

__all__ = [
    # Custom fields
    "get_custom_field_value",
    "extract_custom_fields_dict",
    "ensure_books_custom_fields",
    # Contacts
    "find_contact_by_gstin",
    "find_contact_by_name",
    "fetch_active_customers_map",
    # Items
    "fetch_items_lookup",
    "find_item_by_sku_or_name",
    # Files
    "workdrive_upload_file",
    "attach_file_to_books_resource",
    "workdrive_upload_and_attach",
    # GST
    "GSTIN_PATTERN",
    "normalize_gstin",
    "is_valid_gstin",
    "group_contacts_by_gstin",
    # Dates
    "parse_date",
    "get_month_range",
    "get_previous_month_range",
    # Bank accounts
    "find_bank_account_by_name",
    "fetch_bank_accounts_map",
    # Transactions
    "find_transaction_by_number",
    "unwrap_record",
]
