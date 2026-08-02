"""
Backward compatibility shim for zoho_sdk_advanced exports.
Maps legacy zoho_sdk_advanced imports to zoho.workflows.
"""
import importlib
import sys

from zoho.workflows import (
    fetch_access_tokens,
    get_books_client,
    get_workdrive_client,
    ZohoUsableError,
    ZohoAuthError,
    LedgerParsingError,
    ReconciliationError,
    DotDict,
    clean_ledger_file,
    get_ledger_metadata,
    match_ledger_entries,
    match_bank_with_vendor_ledger,
    reconcile_vendor_account,
    reconcile_vendor,
    parse_zeiss_pdf_statement,
    consolidate_zeiss_statements,
    parse_polycab_credit_memo,
    create_vendor_credit_from_pdf,
    upload_vendor_credit_attachment,
    upload_to_workdrive,
    process_polycab_credit_memos,
    check_vendor_credits_location,
)

_SUBPACKAGES = (
    "bank_reconciliation",
    "core",
    "polycab_credit_memos",
    "vendor_ledger_reconciliation",
)

for _subpackage in _SUBPACKAGES:
    _module = importlib.import_module(f"zoho.workflows.{_subpackage}")
    globals()[_subpackage] = _module
    sys.modules[f"{__name__}.{_subpackage}"] = _module

__all__ = [
    "fetch_access_tokens",
    "get_books_client",
    "get_workdrive_client",
    "ZohoUsableError",
    "ZohoAuthError",
    "LedgerParsingError",
    "ReconciliationError",
    "DotDict",
    "clean_ledger_file",
    "get_ledger_metadata",
    "match_ledger_entries",
    "match_bank_with_vendor_ledger",
    "reconcile_vendor_account",
    "reconcile_vendor",
    "parse_zeiss_pdf_statement",
    "consolidate_zeiss_statements",
    "parse_polycab_credit_memo",
    "create_vendor_credit_from_pdf",
    "upload_vendor_credit_attachment",
    "upload_to_workdrive",
    "process_polycab_credit_memos",
    "check_vendor_credits_location",
    *_SUBPACKAGES,
]
