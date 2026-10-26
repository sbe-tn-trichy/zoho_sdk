from unittest.mock import MagicMock

import pytest

from workflows.collection_reconciliation.bank_statement import (
    bank_line_kind,
    customer_name_suggestions,
    extract_remitter_tokens,
    is_travel_allowance_withdrawal,
)


@pytest.mark.parametrize("description,direction,kind", [
    ("CASH DEPOSIT", "debit", "cash_deposit"),
    ("ATM/Cash Deposit/123", "debit", "cash_deposit"),
    ("CASH DEPOSIT", "credit", "withdrawal"),
    ("NEFT/Salary/September", "credit", "salary"),
    ("Salary", "debit", "deposit"),
    ("UPI/TNPDCL/123", "credit", "electricity"),
    ("upi/tnpdcl123/TA", "credit", "electricity"),
    ("TNPDCL", "debit", "deposit"),
    ("SALARYADVANCE", "credit", "withdrawal"),
])
def test_cash_salary_direction_and_word_boundaries(description, direction, kind):
    assert bank_line_kind({"description": description, "debit_or_credit": direction}) == kind


@pytest.mark.parametrize("kind,direction,description,account_type", [
    ("cash_deposit", "debit", "CASH DEPOSIT/123", "cash"),
    ("salary", "credit", "NEFT/Salary/September", "expense"),
    ("electricity", "credit", "UPI/TNPDCL/123", "expense"),
])
@pytest.mark.parametrize("failure", ["", "changed", "inactive", "wrong_type", "rejected"])
def test_cash_salary_reviewed_posting(tmp_path, kind, direction, description, account_type, failure):
    creator, books = MagicMock(), MagicMock()
    creator.get_all_records.side_effect = [[], []]
    bank = {"transaction_id": "tx", "debit_or_credit": direction,
            "description": description, "date": "2026-10-01", "amount": 1000}
    books.bank_transactions.list_all.return_value = [bank]
    service = OnlinePaymentReviewService(creator, books, OnlinePaymentReviewConfig(
            lazy_invoice_previews=False,
        creator_app_link_name="app", bank_account_id="bank",
        cash_account_id="cash", salary_expense_account_id="salary",
        state_path=tmp_path / "state.json"))
    assert service.refresh()["bank_suggestions"][0]["kind"] == kind
    target = "cash" if kind == "cash_deposit" else "electricity" if kind == "electricity" else "salary"
    books.chart_of_accounts.get.return_value = {"chart_of_account": {
        "account_id": target, "account_type": "bank" if failure == "wrong_type" else account_type,
        "is_active": failure != "inactive"}}
    books.chart_of_accounts.list_all.return_value = [{**books.chart_of_accounts.get.return_value["chart_of_account"], "account_name": "Electricity"}]
    if failure == "changed":
        books.bank_transactions.list_all.return_value = [{**bank, "amount": 999}]
    action = books.bank_transactions.categorize if kind == "cash_deposit" else books.bank_transactions.categorize_as_expense
    action.return_value = {"code": 1 if failure == "rejected" else 0}
    if failure:
        with pytest.raises(ReconciliationError):
            service.categorize_bank_line("tx")
        if failure != "rejected":
            action.assert_not_called()
        assert service.load()["bank_suggestions"][0]["categorization_status"] == "pending"
        return
    assert service.categorize_bank_line("tx")["categorization_status"] == "categorized"
    payload = action.call_args.args[1]
    if kind == "cash_deposit":
        assert payload["from_account_id"] == "cash"
        assert payload["to_account_id"] == "bank"
        assert payload["transaction_type"] == "transfer_fund"
        books.bank_transactions.categorize_as_expense.assert_not_called()
    else:
        assert payload["account_id"] == target
        assert payload["paid_through_account_id"] == "bank"
    service.categorize_bank_line("tx")
    action.assert_called_once()
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
    assert "THANJAVUR" not in tokens_chq


@pytest.mark.parametrize("description", [
    "CHQ DEP - CTS CLG1 - THANJAVUR",
    "chq dep-cts clg1-thanjavur",
    "CHQ DEP - CTS CLG1",
    "CHQ DEP - CTS CLG1 - TRICHY",
    "CHQ DEP - CTS CLG1 - CHENNAI CLEARING CENTRE",
])
def test_cheque_clearing_narration_is_not_customer_evidence(description):
    rows = [{"Customer Name": "Example Customer", "Description": description}]
    assert extract_remitter_tokens(description) == []
    assert customer_name_suggestions({"description": description}, rows) == []


@pytest.mark.parametrize("prefix", ["CHQ DEP - CTS CLG1", "CHQ DEP - CTS CLG1 - THANJAVUR", "CHQ DEP - CTS CLG1 - TRICHY"])
def test_cheque_clearing_prefix_preserves_actual_customer(prefix):
    rows = [{"Customer Name": "Example Customer", "Description": prefix},
            {"Customer Name": "Thanjavur Agencies"},
            {"Customer Name": "Sri Jaikrishna Hardwares", "Description": prefix + ": SRI JAIKRISHNA HARDWARES"}]
    assert customer_name_suggestions(
        {"description": prefix + ": SRI JAIKRISHNA HARDWARES"}, rows
    ) == ["Sri Jaikrishna Hardwares"]


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


@pytest.mark.parametrize("configured_id, active, account_type", [
    ("", True, "expense"),
    ("1094368000029132050", True, "expense"),
    ("1094368000029132050", False, "expense"),
    ("1094368000029132050", True, "bank"),
    ("missing", True, "expense"),
])
def test_travel_expense_requires_live_match_and_explicit_account(tmp_path, configured_id, active, account_type):
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
            lazy_invoice_previews=False,
        creator_app_link_name="app", bank_account_id="bank-1",
        state_path=tmp_path / "state.json",
        travel_expense_account_id=configured_id,
    )
    service = OnlinePaymentReviewService(creator, books, config)
    batch = service.refresh()
    assert batch["bank_suggestions"][0]["kind"] == "travel_allowance"

    books.chart_of_accounts.list_all.return_value = [{
        "account_id": "1094368000029132050", "account_name": "Travel renamed" if configured_id else "Employee Travel Expense",
        "account_type": account_type, "is_active": active,
    }]
    books.chart_of_accounts.get.return_value = {
        "code": 0,
        "chart_of_account": books.chart_of_accounts.list_all.return_value[0],
    }
    if not active or account_type == "bank" or configured_id == "missing":
        with pytest.raises(ReconciliationError, match="active.*account"):
            service.categorize_travel_expense("tx-1")
        books.bank_transactions.categorize_as_expense.assert_not_called()
        return
    books.bank_transactions.categorize_as_expense.return_value = {"code": 0}
    result = service.categorize_travel_expense("tx-1")
    if configured_id:
        books.chart_of_accounts.get.assert_called_once_with(configured_id)
        books.chart_of_accounts.list_all.assert_not_called()
    assert result["categorization_status"] == "categorized"
    books.bank_transactions.categorize_as_expense.assert_called_once_with(
        "tx-1",
        {
            "account_id": "1094368000029132050", "paid_through_account_id": "bank-1",
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
            lazy_invoice_previews=False,
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


@pytest.mark.parametrize("description,direction,expected", [
    ("NEFT/POLY2300277498/TRANSFER", "credit", "vendor_advance"),
    ("neft/poly2300277498/Salary/TA", "withdrawal", "vendor_advance"),
    ("POLY2300277498", "debit", "deposit"),
    ("POLY23002774980", "credit", "withdrawal"),
    ("XPOLY2300277498", "credit", "withdrawal"),
])
def test_polycab_advance_rule(description, direction, expected):
    assert bank_line_kind({"narration": description, "debit_or_credit": direction}) == expected


@pytest.mark.parametrize("failure", ["", "changed", "vendor", "ambiguous", "location", "rejected"])
def test_polycab_advance_reviewed_posting(tmp_path, failure):
    creator, books = MagicMock(), MagicMock()
    creator.get_all_records.side_effect = [[], []]
    bank = {"transaction_id": "poly", "debit_or_credit": "credit",
            "description": "NEFT/POLY2300277498", "date": "2026-10-01", "amount": 1000}
    books.bank_transactions.list_all.return_value = [bank]
    service = OnlinePaymentReviewService(creator, books, OnlinePaymentReviewConfig(
            lazy_invoice_previews=False,
        creator_app_link_name="app", bank_account_id="bank", state_path=tmp_path / "state.json"))
    proposal = service.refresh()["bank_suggestions"][0]
    assert proposal["kind"] == "vendor_advance"
    assert proposal["vendor_name"] == "Polycab"
    assert proposal["location_name"] == "Sri Bharath Electricals"
    assert proposal["customer_suggestions"] == []
    vendor = {"contact_id": "vendor", "contact_name": "Polycab India Limited", "contact_type": "vendor", "status": "active"}
    books.contacts.list_all.return_value = [] if failure == "vendor" else [vendor, vendor] if failure == "ambiguous" else [vendor]
    books.locations.list_all.return_value = [] if failure == "location" else [{"location_id": "sbe", "location_name": "Sri Bharath Electricals", "is_active": True}]
    action = books.bank_transactions.categorize_as_vendor_payment
    action.return_value = {"code": 1 if failure == "rejected" else 0}
    if failure == "changed":
        books.bank_transactions.list_all.return_value = [{**bank, "amount": 999}]
    if failure:
        with pytest.raises(ReconciliationError):
            service.categorize_bank_line("poly")
        if failure != "rejected":
            action.assert_not_called()
        assert service.load()["bank_suggestions"][0]["categorization_status"] == "pending"
    else:
        assert service.categorize_bank_line("poly")["categorization_status"] == "categorized"
        payload = action.call_args.args[1]
        assert payload["vendor_id"] == "vendor"
        assert payload["location_id"] == "sbe"
        assert payload["bills"] == []
        assert payload["paid_through_account_id"] == "bank"
        assert payload["amount"] == 1000
        service.categorize_bank_line("poly")
        action.assert_called_once()
    books.bank_transactions.categorize_as_expense.assert_not_called()


@pytest.mark.parametrize("vpa,expected", [
    ("XXuram@okaxis", ["uram@okaxis"]),
    ("xx3974@ibl", ["3974@ibl"]),
    ("XXXX3974@ibl", ["3974@ibl"]),
    ("XXXXXX@okaxis", []),
])
def test_redacted_upi_search_keeps_suffix_and_handle(vpa, expected):
    assert extract_remitter_tokens("UPI/" + vpa) == expected


def test_redacted_upi_suggestions_include_all_suffix_collisions():
    rows = [
        {"Customer Name": "First Customer", "Description": "UPI/firsturam@okaxis"},
        {"Customer Name": "Second Customer", "Description": "UPI/seconduram@okaxis"},
        {"Customer Name": "Other Handle", "Description": "UPI/firsturam@ybl"},
    ]
    assert customer_name_suggestions({"description": "UPI/XXuram@okaxis"}, rows) == [
        "First Customer", "Second Customer"]


def test_bank_source_retains_all_lines_and_competing_creator_records(tmp_path):
    creator, books = MagicMock(), MagicMock()
    payment = {"ID": "p1", "Payment_Date": "2026-10-01", "Payment_Amount": "1000",
               "Reference": "12345", "Customer_Name": {"ID": "c1", "zc_display_value": "Alice"}}
    creator.get_all_records.side_effect = [[payment, {**payment, "ID": "p2"},
        {**payment, "ID": "posted", "Books_Transaction_Id": "existing"}],
        [{"ID": "c1", "Customer_Id": "customer"}]]
    books.bank_transactions.list_all.return_value = [
        {"transaction_id": "matched", "date": "2026-10-01", "amount": "1000", "reference_number": "12345", "debit_or_credit": "debit"},
        {"transaction_id": "missing", "date": "2026-10-02", "amount": "2000", "debit_or_credit": "debit"},
        {"transaction_id": "expense", "date": "2026-10-01", "amount": "1000", "description": "Alice/TA", "debit_or_credit": "credit"}]
    books.invoices.list_all.return_value = []
    service = OnlinePaymentReviewService(creator, books, OnlinePaymentReviewConfig(
            lazy_invoice_previews=False,
        creator_app_link_name="app", bank_account_id="bank", state_path=tmp_path / "queue.json"))
    batch = service.refresh()
    rows = {row["transaction_id"]: row for row in batch["bank_records"]}
    assert set(rows) == {"matched", "missing", "expense"}
    assert rows["matched"]["creator_entry_ids"] == ["p1", "p2"]
    assert rows["missing"]["creator_entry_ids"] == []
    assert rows["expense"]["creator_entry_ids"] == []
    assert {entry["id"] for entry in batch["entries"]} == {"p1", "p2"}
    books.bank_transactions.list_all.assert_called_once_with(params={"account_id": "bank", "filter_by": "Status.Uncategorized"})
    books.customer_payments.create.assert_not_called()
    assert service.load()["bank_records"] == batch["bank_records"]


@pytest.mark.parametrize("details,date,error", [
    ([], "03-Oct-2026", ""),
    ([{"Cheque_Number": "000432", "Payment_ID.Customer_Name": {"ID": "c"}, "Presented_Date": ""}], "03-Oct-2026", ""),
    ([], "", "No Presented_Date or Cheque_Date is available"),
])
def test_optional_cheque_presentation(details, date, error):
    from workflows.collection_reconciliation.cheques import attach_presented_dates
    payment = {"_review_payment_type": "Cheque", "Reference": "0432", "Customer_Name": {"ID": "c"}, "Cheque_Date": date}
    attach_presented_dates([payment], details)
    assert payment["_review_presented_date"] == date
    assert payment["_review_presented_date_error"] == error


@pytest.mark.parametrize("bank_date,matched", [("2026-10-02", False), ("2026-10-05", True), ("2026-10-11", False)])
def test_cheque_date_fallback_clearing_window(tmp_path, bank_date, matched):
    service = OnlinePaymentReviewService(MagicMock(), MagicMock(), OnlinePaymentReviewConfig(creator_app_link_name="app", bank_account_id="bank", state_path=tmp_path / "q.json"))
    payment = {"date": "2026-10-03", "date_source": "cheque_date", "amount": "5000", "reference": "0432", "payment_type": "Cheque", "date_tolerance_days": 7}
    bank = {"transaction_id": "bank-line", "date": bank_date, "amount": "5000", "reference": "000432"}
    candidate, _ = service._find_transaction(payment, [bank], set())
    assert bool(candidate) is matched
    if not matched:
        with pytest.raises(ReconciliationError):
            service._require_same_date_amount({"creator": payment}, bank)

@pytest.mark.parametrize('payment_type,expected', [('Cheque', '2026-10-05'), ('Online', '2026-10-03')])
def test_books_payment_date_uses_cheque_bank_date_only(tmp_path, payment_type, expected):
    service = OnlinePaymentReviewService(MagicMock(), MagicMock(), OnlinePaymentReviewConfig(creator_app_link_name='app', bank_account_id='bank', state_path=tmp_path / 'q.json'))
    entry = {'id': 'creator', 'payment_type': payment_type, 'bank_account_id': 'bank', 'bank': {'date': '2026-10-05'}, 'creator': {'date': '2026-10-03', 'amount': '5000', 'reference': '0432', 'books_customer_id': 'customer'}}
    assert service._customer_payment_payload(entry, [])['date'] == expected


@pytest.mark.parametrize('existing', [False, True])
def test_cheque_presentation_checkpoint_create_update_and_retry(tmp_path, existing):
    creator = MagicMock()
    service = OnlinePaymentReviewService(creator, MagicMock(), OnlinePaymentReviewConfig(creator_app_link_name='app', bank_account_id='bank', state_path=tmp_path / 'q.json'))
    entry = {'id': '123', 'bank': {'date': '2026-10-05'}, 'creator': {'reference': '0432'}}
    detail = {'ID': 'detail', 'Payment_ID': {'ID': '123'}, 'Cheque_Number': '000432', 'Presented_Date': '03-Oct-2026'}
    verified = {**detail, 'Presented_Date': '05-Oct-2026'}
    creator.get_all_records.side_effect = [[detail] if existing else [], [verified], [verified]]
    creator.add_records.return_value = {'code': 3000}
    creator.update_records.return_value = {'code': 3000}
    service._checkpoint_cheque_presentation(entry)
    service._checkpoint_cheque_presentation(entry)
    assert all(call.kwargs == {"field_config": "all"} for call in creator.get_all_records.call_args_list)
    action = creator.update_records if existing else creator.add_records
    action.assert_called_once()
    payload = action.call_args.args[2]['data']
    assert payload['Presented_Date'] == '05-Oct-2026'
    assert payload['Payment_ID'] == '123'


@pytest.mark.parametrize('failure', ['duplicate', 'wrong_cheque', 'rejected', 'readback'])
def test_cheque_presentation_checkpoint_blocks_errors(tmp_path, failure):
    creator = MagicMock()
    service = OnlinePaymentReviewService(creator, MagicMock(), OnlinePaymentReviewConfig(creator_app_link_name='app', bank_account_id='bank', state_path=tmp_path / 'q.json'))
    entry = {'id': '123', 'bank': {'date': '2026-10-05'}, 'creator': {'reference': '0432'}}
    detail = {'ID': 'detail', 'Payment_ID': {'ID': '123'}, 'Cheque_Number': '9999' if failure == 'wrong_cheque' else '0432', 'Presented_Date': '03-Oct-2026'}
    creator.get_all_records.side_effect = [[detail, detail] if failure == 'duplicate' else [detail], [detail]]
    creator.update_records.return_value = {'code': 3001 if failure == 'rejected' else 3000}
    with pytest.raises(ReconciliationError):
        service._checkpoint_cheque_presentation(entry)
    if failure in {'duplicate', 'wrong_cheque'}:
        creator.update_records.assert_not_called()
    creator.add_records.assert_not_called()
