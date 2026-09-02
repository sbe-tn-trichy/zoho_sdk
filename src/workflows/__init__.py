"""Public workflow API with dependency-light, lazy domain exports."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

from .core.auth import (
    fetch_access_tokens,
    get_books_client,
    get_workdrive_client,
)
from .core.exceptions import (
    LedgerParsingError,
    ReconciliationError,
    SchemaValidationError,
    ZohoAuthError,
    ZohoUsableError,
)
from .core.models import DotDict


_LAZY_EXPORTS: Dict[str, Tuple[str, str]] = {
    "CollectionReconciler": (".collection_reconciliation", "CollectionReconciler"),
    "CollectionReconciliationConfig": (".collection_reconciliation", "CollectionReconciliationConfig"),
    "OnlinePaymentReviewConfig": (".collection_reconciliation", "OnlinePaymentReviewConfig"),
    "OnlinePaymentReviewService": (".collection_reconciliation", "OnlinePaymentReviewService"),
    "REQUIRED_OAUTH_SCOPES": (".collection_reconciliation", "REQUIRED_OAUTH_SCOPES"),
    "missing_oauth_scopes": (".collection_reconciliation", "missing_oauth_scopes"),
    "reconcile_collections": (".collection_reconciliation", "reconcile_collections"),
    "check_vendor_credits_location": (".polycab_credit_memos.processor", "check_vendor_credits_location"),
    "create_vendor_credit_from_pdf": (".polycab_credit_memos.processor", "create_vendor_credit_from_pdf"),
    "parse_polycab_credit_memo": (".polycab_credit_memos.processor", "parse_polycab_credit_memo"),
    "process_polycab_credit_memos": (".polycab_credit_memos.processor", "process_polycab_credit_memos"),
    "upload_to_workdrive": (".polycab_credit_memos.processor", "upload_to_workdrive"),
    "upload_vendor_credit_attachment": (".polycab_credit_memos.processor", "upload_vendor_credit_attachment"),
    "import_polycab_rso_pdf": (".polycab_rso", "import_polycab_rso_pdf"),
    "parse_polycab_rso_pdf": (".polycab_rso", "parse_polycab_rso_pdf"),
    "clean_ledger_file": (".vendor_ledger_reconciliation.cleaner", "clean_ledger_file"),
    "get_ledger_metadata": (".vendor_ledger_reconciliation.cleaner", "get_ledger_metadata"),
    "match_bank_with_vendor_ledger": (".bank_vendor_ledger_matching.matcher", "match_bank_with_vendor_ledger"),
    "match_ledger_entries": (".bank_vendor_ledger_matching.matcher", "match_ledger_entries"),
    "reconcile_vendor": (".vendor_ledger_reconciliation.matcher", "reconcile_vendor"),
    "reconcile_vendor_account": (".vendor_ledger_reconciliation.matcher", "reconcile_vendor_account"),
    "consolidate_zeiss_statements": (".vendor_ledger_reconciliation.zeiss_pdf", "consolidate_zeiss_statements"),
    "parse_zeiss_pdf_statement": (".vendor_ledger_reconciliation.zeiss_pdf", "parse_zeiss_pdf_statement"),
    "GSTR1VerificationConfig": (".gstr1_verification", "GSTR1VerificationConfig"),
    "GSTR1Verifier": (".gstr1_verification", "GSTR1Verifier"),
    "verify_gstr1": (".gstr1_verification", "verify_gstr1"),
    "DuplicatePaymentChecker": (".duplicate_payment_check", "DuplicatePaymentChecker"),
    "check_duplicate_payments": (".duplicate_payment_check", "check_duplicate_payments"),
    "CreatorCustomerDeleteSyncConfig": (".creator_customer_delete_sync", "CreatorCustomerDeleteSyncConfig"),
    "CreatorCustomerDeleteSyncer": (".creator_customer_delete_sync", "CreatorCustomerDeleteSyncer"),
    "sync_creator_customer_deletions": (".creator_customer_delete_sync", "sync_creator_customer_deletions"),
    "NeosealItemAuditor": (".neoseal_audit", "NeosealItemAuditor"),
    "audit_neoseal_items": (".neoseal_audit", "audit_neoseal_items"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    try:
        module = import_module(module_name, __name__)
    except ModuleNotFoundError as exc:
        if exc.name in {"pdfplumber", "xlrd", "openpyxl", "pandas", "dotenv"}:
            raise ModuleNotFoundError(
                f"Workflow {name!r} requires optional dependencies; install "
                "zoho-sdk[workflows]."
            ) from exc
        raise
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))

__all__ = [
    "fetch_access_tokens",
    "get_books_client",
    "get_workdrive_client",
    "ZohoUsableError",
    "ZohoAuthError",
    "LedgerParsingError",
    "ReconciliationError",
    "SchemaValidationError",
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
    "parse_polycab_rso_pdf",
    "import_polycab_rso_pdf",
    "CollectionReconciler",
    "CollectionReconciliationConfig",
    "reconcile_collections",
    "OnlinePaymentReviewConfig",
    "OnlinePaymentReviewService",
    "REQUIRED_OAUTH_SCOPES",
    "missing_oauth_scopes",
    "GSTR1VerificationConfig",
    "GSTR1Verifier",
    "verify_gstr1",
    "DuplicatePaymentChecker",
    "check_duplicate_payments",
    "CreatorCustomerDeleteSyncConfig",
    "CreatorCustomerDeleteSyncer",
    "sync_creator_customer_deletions",
    "NeosealItemAuditor",
    "audit_neoseal_items",
]
