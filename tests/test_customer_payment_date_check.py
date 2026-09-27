from decimal import Decimal
from unittest.mock import Mock

import pytest

from workflows.customer_payment_date_check import (
    AnalyticsCustomerPaymentDateChecker,
    CustomerPaymentDateUpdater,
    check_customer_payment_dates_analytics,
    render_csv_report,
    render_markdown_report,
)


def test_process_rows_no_mismatch():
    checker = AnalyticsCustomerPaymentDateChecker(Mock())
    rows = [
        {
            "Payment ID": "CP1",
            "Payment Number": "PMT-001",
            "Payment Date": "2025-08-01",
            "Customer ID": "CUST1",
            "Customer Name": "Acme Corp",
            "Payment_Amount": 1000.0,
            "Unused Amount": 0.0,
            "Reference Number": "REF123",
            "Payment Mode": "online",
            "Invoice Number": "INV-001",
            "Invoice Date": "2025-07-25",
            "Invoice Payment Applied Date": "2025-08-01",
            "Amount Applied": 1000.0,
        }
    ]
    result = checker.process_rows(rows)
    assert result["payments_scanned"] == 1
    assert result["mismatched_payments_count"] == 0


def test_process_rows_with_mismatch():
    checker = AnalyticsCustomerPaymentDateChecker(Mock())
    rows = [
        {
            "Payment ID": "CP2",
            "Payment Number": "PMT-002",
            "Payment Date": "2025-08-01",
            "Customer ID": "CUST1",
            "Customer Name": "Acme Corp",
            "Payment_Amount": 1500.0,
            "Unused Amount": 500.0,
            "Reference Number": "REF456",
            "Payment Mode": "banktransfer",
            "Invoice Number": "INV-001",
            "Invoice Date": "2025-07-25",
            "Invoice Payment Applied Date": "2025-08-10",
            "Amount Applied": 1000.0,
            "Mismatch Type": "Applied After Payment",
        }
    ]
    result = checker.process_rows(rows)
    assert result["payments_scanned"] == 1
    assert result["mismatched_payments_count"] == 1
    assert result["total_mismatched_applications"] == 1
    pmt = result["mismatches"][0]
    assert pmt["payment_id"] == "CP2"
    assert len(pmt["mismatched_applications"]) == 1
    app = pmt["mismatched_applications"][0]
    assert app["invoice_number"] == "INV-001"
    assert app["applied_date"] == "2025-08-10"
    assert app["days_difference"] == 9
    assert app["mismatch_type"] == "Applied After Payment"


def test_process_rows_tolerance():
    checker = AnalyticsCustomerPaymentDateChecker(Mock())
    rows = [
        {
            "Payment ID": "CP3",
            "Payment Number": "PMT-003",
            "Payment Date": "2025-08-01",
            "Customer ID": "CUST2",
            "Customer Name": "Beta LLC",
            "Invoice Number": "INV-002",
            "Invoice Payment Applied Date": "2025-08-03",
            "Amount Applied": 500.0,
        }
    ]
    assert checker.process_rows(rows, tolerance_days=3)["mismatched_payments_count"] == 0
    assert checker.process_rows(rows, tolerance_days=1)["mismatched_payments_count"] == 1


def test_analytics_client_execution():
    analytics = Mock()
    analytics.views.export_all.return_value = [
        {
            "Payment ID": "CP1",
            "Payment Number": "PMT-001",
            "Payment Date": "2025-08-01",
            "Customer Name": "Test",
            "Invoice Number": "INV-1",
            "Invoice Payment Applied Date": "2025-08-05",
            "Amount Applied": 100.0,
        }
    ]

    result = check_customer_payment_dates_analytics(analytics, from_date="2025-08-01", to_date="2025-08-31")
    assert result["payments_scanned"] == 1
    assert result["mismatched_payments_count"] == 1
    analytics.views.export_all.assert_called_once()


def test_updater_dry_run_and_execute():
    books = Mock()
    books.customer_payments.get.return_value = {
        "payment": {
            "payment_id": "P1",
            "invoices": [
                {"invoice_id": "INV1", "amount_applied": 500.0, "date": "2026-02-14"}
            ]
        }
    }
    updater = CustomerPaymentDateUpdater(books)

    plan = {
        "by_payment": {
            "P1": [
                {
                    "payment_id": "P1",
                    "payment_number": "PMT-1",
                    "customer_name": "Test",
                    "invoice_id": "INV1",
                    "target_applied_date": "2026-01-29",
                }
            ]
        }
    }

    # Dry run
    dry_result = updater.execute_plan(plan, execute=False)
    assert dry_result["summary"]["dry_run"] is True
    assert dry_result["summary"]["planned"] == 1
    books.customer_payments.update.assert_not_called()

    # Live execution
    live_result = updater.execute_plan(plan, execute=True)
    assert live_result["summary"]["dry_run"] is False
    assert live_result["summary"]["updated"] == 1
    books.customer_payments.update.assert_called_once_with(
        "P1",
        {"invoices": [{"invoice_id": "INV1", "amount_applied": 500.0, "date": "2026-01-29", "apply_date": "2026-01-29"}]}
    )


def test_build_update_plan():
    from workflows.customer_payment_date_check import build_update_plan
    audit_data = {
        "result": {
            "mismatches": [
                {
                    "payment_id": "P100",
                    "payment_number": "PMT-100",
                    "payment_date": "2025-08-01",
                    "customer_name": "Test Cust",
                    "mismatched_applications": [
                        {
                            "invoice_id": "INV-A",
                            "invoice_number": "INV-001",
                            "invoice_date": "2025-07-15",
                            "applied_date": "2025-09-01",
                            "amount_applied": "1,500.00",
                        },
                        {
                            "invoice_id": "INV-B",
                            "invoice_number": "INV-002",
                            "invoice_date": "2025-08-10",
                            "applied_date": "2025-07-01",
                            "amount_applied": "2,000.00",
                        },
                    ],
                }
            ]
        }
    }
    plan = build_update_plan(audit_data)
    assert plan["total_discrepancies"] == 2
    assert plan["distinct_payments_count"] == 1
    allocations = plan["allocations"]
    # INV-A: max(2025-08-01, 2025-07-15) -> 2025-08-01 (Payment Date)
    assert allocations[0]["target_applied_date"] == "2025-08-01"
    assert allocations[0]["target_date_source"] == "Payment Date"
    # INV-B: max(2025-08-01, 2025-08-10) -> 2025-08-10 (Invoice Date)
    assert allocations[1]["target_applied_date"] == "2025-08-10"
    assert allocations[1]["target_date_source"] == "Invoice Date"

