"""Explicit Analytics consumers; names resolve to stable IDs in each workspace."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class WorkflowViewReference:
    workflow_key: str
    view_name: str
    source_file: str
    usage_type: Literal["read", "create", "update"] = "read"
    view_id: str = ""
    notes: str = ""


def _references(key: str, source: str, names: tuple[str, ...]) -> tuple[WorkflowViewReference, ...]:
    return tuple(WorkflowViewReference(key, name, source) for name in names)


DEFAULT_REFERENCES = (
    WorkflowViewReference("bank_statement_check", "Bank Statements (Zoho Books)",
                          "src/workflows/bank_statement_check.py", view_id="264324000005829009",
                          notes="Read-only HDFC CSV completeness comparison; configurable view ID requires an explicit runtime reference."),
    *_references("unearned_revenue", "src/workflows/unearned_revenue.py",
                 ("Customer Payments (Zoho Books)", "Customers (Zoho Books)",
                  "Accrual Transactions (Zoho Books)", "Accounts (Zoho Books)")),
    WorkflowViewReference("detailed_general_ledger", "detailed general ledger",
                          "okf/analytics-metadata.md", view_id="264324000008493010",
                          notes="FY 2025-26 accrual postings joined to account name and account type."),
    WorkflowViewReference("undeposited_deposit_report", "Undeposited Funds - Deposits and Payment Candidates",
                          "okf/analytics-metadata.md", view_id="264324000008503027",
                          notes="Deposit summary for account 1094368000000000456; inferred payment candidates, not confirmed associations."),
    WorkflowViewReference("undeposited_deposit_report", "Undeposited Funds - Deposit Report",
                          "okf/analytics-metadata.md", view_id="264324000008503041",
                          notes="Summary report consuming the deposit candidate query table."),
    WorkflowViewReference("undeposited_deposit_report", "Undeposited Funds - Deposits and Payment Candidates",
                          "okf/analytics-metadata.md", view_id="264324000008503027",
                          notes="Deposit summary for account 1094368000000000456; inferred payment candidates, not confirmed associations."),
    WorkflowViewReference("undeposited_deposit_report", "Undeposited Funds - Deposit Report",
                          "okf/analytics-metadata.md", view_id="264324000008503041",
                          notes="Summary report consuming the deposit candidate query table."),
    WorkflowViewReference("customer_payment_date_check", "Customer Payment vs Applied Date Mismatch",
                          "src/workflows/customer_payment_date_check/checker.py",
                          view_id="264324000008269008", notes="Default ID; supply an override for custom deployments."),
    *_references("collection_reconciliation", "src/workflows/collection_reconciliation/reconciler.py",
                 ("Bank Transactions", "Customer Master")),
    *_references("payment_review", "src/workflows/collection_reconciliation/review.py",
                 ("Payment Customer Finder",)),
    *_references("gstr1_verification", "src/workflows/gstr1_verification/analytics.py",
                 ("Locations (Zoho Books)", "Invoices (Zoho Books)", "Credit Notes (Zoho Books)")),
    *_references("gstr1_verification", "src/workflows/gstr1_verification/hsn.py",
                 ("Credit Notes (Zoho Books)", "Credit Note Items (Zoho Books)",
                  "Invoices (Zoho Books)", "Invoice Items (Zoho Books)", "Customers (Zoho Books)")),
    *_references("gstr2_verification", "apps/verify_gstr2.py",
                 ("Bills (Zoho Books)", "Vendors (Zoho Books)", "Expenses (Zoho Books)", "Vendor Credits (Zoho Books)")),
    *_references("payment_inspection", "src/workflows/payment_inspection.py", ("Customer Payments (Zoho Books)",)),
    *_references("payment_renumbering", "src/workflows/payment_renumbering/engine.py", ("Customer Payments (Zoho Books)",)),
    *_references("inter_location_analytics_report", "src/workflows/inter_location_analytics_report.py",
                 ("Customer Payments (Zoho Books)", "Vendor Payments (Zoho Books)", "Locations (Zoho Books)",
                  "Manual Journal Items (Zoho Books)", "Manual Journals (Zoho Books)", "Accounts (Zoho Books)",
                  "Invoice Payments (Zoho Books)", "Invoices (Zoho Books)", "Payments Made (Zoho Books)", "Bills (Zoho Books)")),
    *_references("inter_location_payment_proposals", "src/workflows/inter_location_payment_proposals.py",
                 ("Customer Payments (Zoho Books)", "Vendor Payments (Zoho Books)", "Invoice Payments (Zoho Books)",
                  "Invoices (Zoho Books)", "Payments Made (Zoho Books)", "Bills (Zoho Books)")),
    *_references("monthly_gst_analytics", "apps/check_monthly_gst_analytics.py",
                 ("Accounts (Zoho Books)", "Accrual Transactions (Zoho Books)")),
    WorkflowViewReference("inter_location_analytics_report", "", "src/workflows/inter_location_analytics_report.py",
                          "update", "264324000008274019", "Default managed query table."),
    WorkflowViewReference("inter_location_contra", "", "apps/review_inter_location_contra.py",
                          view_id="264324000006990003", notes="Default location-difference evidence view."),
    WorkflowViewReference("inter_location_payment_proposals", "", "apps/propose_inter_location_payment_updates.py",
                          view_id="264324000008274019"),
    WorkflowViewReference("inter_location_contra", "", "apps/propose_inter_location_updates.py",
                          view_id="264324000008274019"),
)
