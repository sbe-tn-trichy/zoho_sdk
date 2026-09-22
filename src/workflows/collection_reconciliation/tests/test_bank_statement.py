from unittest.mock import MagicMock

import pytest

from workflows.collection_reconciliation.bank_statement import (
    customer_name_suggestions,
    extract_remitter_tokens,
    is_travel_allowance_withdrawal,
)
from workflows.collection_reconciliation.review import OnlinePaymentReviewConfig, OnlinePaymentReviewService
from workflows.core.exceptions import ReconciliationError


def test_extract_remitter_tokens_handles_upi_and_neft():
    upi_desc = "UPI/135421680729/Payment from Ph/8015093974@ibl/State Bank Of I/IBLc1b338a963424ce7a0a41b88a4055990"
    tokens = extract_remitter_tokens(upi_desc)
    assert "8015093974@ibl" in tokens
    assert "8015093974" in tokens

    neft_desc = "NEFT-002984487856-CHENDURS AGENCIES-URGENT-xxxxxxxxxxx6216-UBIN0538892"
    tokens_neft = extract_remitter_tokens(neft_desc)
    assert "CHENDURS AGENCIES" in tokens_neft

    cheque_desc = "CHQ DEP - CTS CLG1 - THANJAVUR: SRI JAIKRISHNA HARDWARES AND ELECTRICALS :INDIAN BANK"
    tokens_chq = extract_remitter_tokens(cheque_desc)
    assert "SRI JAIKRISHNA HARDWARES AND ELECTRICALS" in tokens_chq


def test_customer_name_suggested_from_neft_narration():
    bank = {"description": "NEFT-002984487856-CHENDURS AGENCIES-URGENT-xxxxxxxxxxx6216-UBIN0538892"}
    rows = [{"Customer Name": "Chendurs Agencies - Pudukkottai"}, {"Customer Name": "Other Agencies"}]
    assert customer_name_suggestions(bank, rows) == ["Chendurs Agencies - Pudukkottai"]


def test_customer_name_suggested_from_finder_description():
    bank = {"description": "NEFT/REFERENCE123/UNKNOWN REMITTER"}
    rows = [{
        "Description": "NEFT/REFERENCE123/UNKNOWN REMITTER",
        "Customer Name": "Chendurs Agencies",
    }]
    assert customer_name_suggestions(bank, rows) == ["Chendurs Agencies"]


def test_ta_suffix_requires_withdrawal():
    description = "NEFT/IDFB6258M0201962/Naveenkumar Arivazhagan/IDIB000B064/TA"
    assert is_travel_allowance_withdrawal({"transaction_type": "uncategorized", "debit_or_credit": "credit", "description": description})
    assert not is_travel_allowance_withdrawal({"transaction_type": "uncategorized", "debit_or_credit": "debit", "description": description})
    assert not is_travel_allowance_withdrawal({"debit_or_credit": "credit", "description": description + "/OTHER"})


def test_travel_expense_requires_live_match_and_explicit_account(tmp_path):
    creator, books = MagicMock(), MagicMock()
    creator.get_all_records.side_effect = [[], []]
    bank = {
        "transaction_id": "tx-1", "transaction_type": "uncategorized", "debit_or_credit": "credit",
        "date": "2026-09-20", "amount": 500,
        "description": "NEFT/123/Naveenkumar/IDIB000B064/TA",
        "reference_number": "NEFT-123",
    }
    books.bank_transactions.list_all.return_value = [bank]
    config = OnlinePaymentReviewConfig(
        creator_app_link_name="app", bank_account_id="bank-1",
        state_path=tmp_path / "state.json",
    )
    service = OnlinePaymentReviewService(creator, books, config)
    batch = service.refresh()
    assert batch["bank_suggestions"][0]["kind"] == "travel_allowance"

    books.chart_of_accounts.list_all.return_value = [{
        "account_id": "expense-1", "account_name": "Employee Travel Expense",
        "account_type": "expense", "is_active": True,
    }]
    books.bank_transactions.categorize_as_expense.return_value = {"code": 0}
    result = service.categorize_travel_expense("tx-1")
    assert result["categorization_status"] == "categorized"
    books.bank_transactions.categorize_as_expense.assert_called_once_with(
        "tx-1",
        {
            "account_id": "expense-1", "paid_through_account_id": "bank-1",
            "date": "2026-09-20", "amount": 500.0,
            "description": bank["description"], "reference_number": "NEFT-123",
        },
    )
    books.bank_transactions.list_all.return_value = []
    assert service.categorize_travel_expense("tx-1")["categorization_status"] == "categorized"
    books.bank_transactions.categorize_as_expense.assert_called_once()


@pytest.mark.parametrize("direction, expected_kind", [("debit", "deposit"), ("credit", "withdrawal")])
def test_other_bank_line_gets_analytics_narration_suggestion(tmp_path, direction, expected_kind):
    creator, books, analytics = MagicMock(), MagicMock(), MagicMock()
    creator.get_all_records.side_effect = [[], []]
    books.bank_transactions.list_all.return_value = [{
        "transaction_id": "line-1", "debit_or_credit": direction,
        "date": "2026-09-20", "amount": 1000,
        "description": "NEFT-002984487856-CHENDURS AGENCIES-URGENT-xxxx6216",
    }]
    analytics.views.export_all.return_value = [{"Customer Name": "Chendurs Agencies"}]
    service = OnlinePaymentReviewService(
        creator, books,
        OnlinePaymentReviewConfig(
            creator_app_link_name="app", bank_account_id="bank-1",
            analytics_workspace_id="workspace", customer_finder_view_id="view",
            state_path=tmp_path / "state.json",
        ),
        analytics_client=analytics,
    )

    suggestion = service.refresh()["bank_suggestions"][0]
    assert suggestion["kind"] == expected_kind
    assert suggestion["customer_suggestions"] == ["Chendurs Agencies"]
    books.bank_transactions.categorize_as_expense.assert_not_called()
