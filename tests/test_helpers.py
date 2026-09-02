"""Unit tests for zoho.helpers modules."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from decimal import Decimal

from zoho.helpers import (
    GSTIN_PATTERN,
    allocate_documents_fifo,
    attach_file_to_books_resource,
    ensure_books_custom_fields,
    extract_bank_deposits,
    extract_bank_withdrawals,
    extract_custom_fields_dict,
    fetch_active_customers_map,
    fetch_bank_accounts_map,
    fetch_items_by_purchase_account,
    fetch_items_lookup,
    fetch_open_bills,

    fetch_open_invoices,
    find_bank_account_by_name,
    find_bill_by_number,
    find_contact_by_gstin,
    find_contact_by_name,
    find_item_by_sku_or_name,
    find_transaction_by_number,
    get_custom_field_value,
    get_financial_year_range,
    get_month_range,
    get_previous_month_range,
    group_contacts_by_gstin,
    is_valid_gstin,
    normalize_cheque_number,
    normalize_gstin,
    parse_date,
    unwrap_record,
    workdrive_upload_and_attach,
    workdrive_upload_file,
)



class TestCustomFieldsHelper:
    def test_get_custom_field_value_direct_key(self):
        record = {"cf_gstin": "33AAAAA0000A1Z5", "contact_id": "1001"}
        assert get_custom_field_value(record, "cf_gstin") == "33AAAAA0000A1Z5"
        assert get_custom_field_value(record, "missing_field", default="N/A") == "N/A"

    def test_get_custom_field_value_from_list(self):
        record = {
            "contact_id": "1001",
            "custom_fields": [
                {"api_name": "cf_gst_number", "label": "GST Number", "value": "33AAAAA0000A1Z5"},
                {"customfield_id": "99001", "label": "Sales Person", "value": "John Doe"},
            ],
        }
        # By api_name
        assert get_custom_field_value(record, "cf_gst_number") == "33AAAAA0000A1Z5"
        # By label
        assert get_custom_field_value(record, "gst number") == "33AAAAA0000A1Z5"
        # By customfield_id
        assert get_custom_field_value(record, "99001") == "John Doe"
        # Missing
        assert get_custom_field_value(record, "non_existent") is None

    def test_get_custom_field_value_from_hash(self):
        record = {
            "contact_id": "1001",
            "custom_field_hash": {"cf_pan": "ABCDE1234F"},
        }
        assert get_custom_field_value(record, "cf_pan") == "ABCDE1234F"

    def test_extract_custom_fields_dict(self):
        record = {
            "contact_id": "1001",
            "custom_fields": [
                {"api_name": "cf_region", "value": "South"},
                {"label": "Territory", "value": "TN"},
            ],
            "custom_field_hash": {"cf_legacy_id": "999"},
        }
        extracted = extract_custom_fields_dict(record)
        assert extracted["cf_region"] == "South"
        assert extracted["Territory"] == "TN"
        assert extracted["cf_legacy_id"] == "999"

    def test_ensure_books_custom_fields(self):
        mock_books = MagicMock()
        mock_books.custom_fields.list_for_entity.return_value = [
            {"label": "Creator Record ID", "data_type": "string", "is_unique": True}
        ]
        requirements = [
            {"label": "Creator Record ID", "data_type": "string", "is_unique": True},
            {"label": "Creator Payment ID", "data_type": "number", "is_unique": True},
        ]
        mock_books.custom_fields.create.return_value = {"customfield_id": "CF_NEW"}

        result = ensure_books_custom_fields(
            mock_books,
            entity="customer_payment",
            requirements=requirements,
            create_missing=True,
        )
        assert result["valid"] is True
        assert len(result["created"]) == 1
        mock_books.custom_fields.create.assert_called_once_with(requirements[1])


class TestGSTHelper:
    def test_normalize_gstin(self):
        assert normalize_gstin(" 33abcde1234f1z5 ") == "33ABCDE1234F1Z5"
        assert normalize_gstin("33-ABCDE-1234-F1Z5") == "33ABCDE1234F1Z5"
        assert normalize_gstin(None) == ""

    def test_is_valid_gstin(self):
        assert is_valid_gstin("33ABCDE1234F1Z5") is True
        assert is_valid_gstin("invalid_gstin") is False
        assert is_valid_gstin("33ABCDE1234F1Z") is False

    def test_group_contacts_by_gstin(self):
        contacts = [
            {"contact_id": "C1", "gst_no": "33ABCDE1234F1Z5"},
            {"contact_id": "C2", "custom_fields": [{"api_name": "gstin", "value": "33ABCDE1234F1Z5"}]},
            {"contact_id": "C3", "gst_no": "33XYZAB9999K1Z2"},
            {"contact_id": "C4", "gst_no": "INVALID"},
        ]
        grouped = group_contacts_by_gstin(contacts)
        assert "33ABCDE1234F1Z5" in grouped
        assert len(grouped["33ABCDE1234F1Z5"]) == 2
        assert "33XYZAB9999K1Z2" in grouped
        assert "INVALID" not in grouped


class TestDatesHelper:
    def test_parse_date(self):
        assert parse_date("2026-08-15") == date(2026, 8, 15)
        assert parse_date("15-08-2026") == date(2026, 8, 15)
        assert parse_date("15/08/2026") == date(2026, 8, 15)
        assert parse_date("15-Aug-2026") == date(2026, 8, 15)
        assert parse_date("15-Aug-26") == date(2026, 8, 15)
        assert parse_date(date(2026, 8, 15)) == date(2026, 8, 15)
        assert parse_date("invalid-date") is None
        assert parse_date(None) is None

    def test_get_month_range(self):
        start, end = get_month_range("2026-02")
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

        start_leap, end_leap = get_month_range("2024-02")
        assert start_leap == date(2024, 2, 1)
        assert end_leap == date(2024, 2, 29)

        with pytest.raises(ValueError):
            get_month_range("invalid")

    def test_get_previous_month_range(self):
        as_of = date(2026, 3, 15)
        start, end = get_previous_month_range(as_of)
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_get_financial_year_range(self):
        # Default start_month = 4 (Indian FY)
        start, end = get_financial_year_range(date(2026, 8, 15))
        assert start == date(2026, 4, 1)
        assert end == date(2027, 3, 31)

        start_jan, end_jan = get_financial_year_range(date(2026, 2, 10))
        assert start_jan == date(2025, 4, 1)
        assert end_jan == date(2026, 3, 31)

        # Calendar year FY (start_month = 1)
        start_cal, end_cal = get_financial_year_range(date(2026, 7, 1), start_month=1)
        assert start_cal == date(2026, 1, 1)
        assert end_cal == date(2026, 12, 31)

        with pytest.raises(ValueError):
            get_financial_year_range(start_month=13)



class TestAccountsHelper:
    def test_find_bank_account_by_name(self):
        mock_books = MagicMock()
        mock_books.bank_accounts.list_all.return_value = [
            {"account_id": "B100", "account_name": "Vendor To Customer"},
            {"account_id": "B200", "account_name": "ICICI Current"},
        ]
        res = find_bank_account_by_name(mock_books, "vendor to customer")
        assert res is not None
        assert res["account_id"] == "B100"

        assert find_bank_account_by_name(mock_books, "NonExistent") is None

    def test_fetch_bank_accounts_map(self):
        mock_books = MagicMock()
        mock_books.bank_accounts.list_all.return_value = [
            {"account_id": "B100", "account_name": "HDFC Clearing"},
            {"account_id": "B200", "account_name": "IDFC Petty Cash"},
        ]
        acc_map = fetch_bank_accounts_map(mock_books)
        assert "hdfc clearing" in acc_map
        assert acc_map["hdfc clearing"]["account_id"] == "B100"
        assert "idfc petty cash" in acc_map

    def test_extract_bank_withdrawals_and_deposits(self):
        txs = [
            {"transaction_id": "T1", "amount": -500.0, "debit_or_credit": "debit"},
            {"transaction_id": "T2", "amount": 1200.0, "debit_or_credit": "credit"},
            {"transaction_id": "T3", "amount": 300.0, "transaction_type": "expense"},
            {"transaction_id": "T4", "amount": 450.0, "transaction_type": "deposit"},
        ]
        withdrawals = extract_bank_withdrawals(txs)
        assert len(withdrawals) == 2
        assert {w["transaction_id"] for w in withdrawals} == {"T1", "T3"}

        deposits = extract_bank_deposits(txs)
        assert len(deposits) == 2
        assert {d["transaction_id"] for d in deposits} == {"T2", "T4"}



class TestTransactionsHelper:
    def test_unwrap_record(self):
        resp_so = {"code": 0, "salesorder": {"salesorder_id": "SO_123", "total": 100}}
        assert unwrap_record(resp_so)["salesorder_id"] == "SO_123"

        resp_pay = {"payment": {"payment_id": "PAY_99"}}
        assert unwrap_record(resp_pay)["payment_id"] == "PAY_99"

        flat = {"invoice_id": "INV_1"}
        assert unwrap_record(flat)["invoice_id"] == "INV_1"

    def test_find_transaction_by_number(self):
        mock_resource = MagicMock()
        mock_resource.list_all.return_value = [
            {"salesorder_id": "SO1", "salesorder_number": "SO-001", "reference_number": "REF-100"},
            {"salesorder_id": "SO2", "salesorder_number": "SO-002", "reference_number": "REF-200"},
        ]

        # Search by reference number
        match1 = find_transaction_by_number(mock_resource, "REF-100")
        assert match1 is not None
        assert match1["salesorder_id"] == "SO1"

        # Search by salesorder number
        match2 = find_transaction_by_number(mock_resource, "SO-002")
        assert match2 is not None
        assert match2["salesorder_id"] == "SO2"

        # Not found
        assert find_transaction_by_number(mock_resource, "REF-999") is None

    def test_normalize_cheque_number(self):
        assert normalize_cheque_number("000452") == "452"
        assert normalize_cheque_number("000123") == "123"
        assert normalize_cheque_number("CHQ-00123") == "chq00123"
        assert normalize_cheque_number(" 000 ") == "0"
        assert normalize_cheque_number(None) == ""
        assert normalize_cheque_number("") == ""


    def test_fetch_open_invoices_and_bills(self):
        mock_books = MagicMock()
        mock_books.invoices.list_all.return_value = [
            {"invoice_id": "INV-1", "status": "sent", "balance": 100.0},
            {"invoice_id": "INV-2", "status": "paid", "balance": 0.0},
            {"invoice_id": "INV-3", "status": "draft", "balance": 50.0},
            {"invoice_id": "INV-4", "status": "overdue", "balance": 250.0},
        ]
        mock_books.bills.list_all.return_value = [
            {"bill_id": "BILL-1", "status": "open", "balance": 400.0},
            {"bill_id": "BILL-2", "status": "void", "balance": 300.0},
        ]

        invoices = fetch_open_invoices(mock_books, "CUST-1")
        assert len(invoices) == 2
        assert {inv["invoice_id"] for inv in invoices} == {"INV-1", "INV-4"}

        bills = fetch_open_bills(mock_books, "VEND-1")
        assert len(bills) == 1
        assert bills[0]["bill_id"] == "BILL-1"

        assert fetch_open_invoices(mock_books, "") == []
        assert fetch_open_bills(mock_books, "") == []

    def test_find_bill_by_number(self):
        mock_books = MagicMock()
        mock_books.bills.list.return_value = {
            "bills": [
                {"bill_id": "B-100", "bill_number": "BILL/2026/01"},
            ]
        }
        bill = find_bill_by_number(mock_books, "V-1", "BILL/2026/01")
        assert bill is not None
        assert bill["bill_id"] == "B-100"

        assert find_bill_by_number(mock_books, "V-1", "") is None

    def test_allocate_documents_fifo(self):
        invoices = [
            {"invoice_id": "INV-1", "due_date": "2026-02-01", "date": "2026-01-01", "balance": 100.0},
            {"invoice_id": "INV-2", "due_date": "2026-01-15", "date": "2026-01-01", "balance": 150.0},
            {"invoice_id": "INV-3", "due_date": "2026-03-01", "date": "2026-02-01", "balance": 200.0},
        ]

        # Allocation without metadata
        allocs, unalloc = allocate_documents_fifo(200.0, invoices, id_key="invoice_id")
        assert unalloc == Decimal("0")
        assert len(allocs) == 2
        # INV-2 is oldest due date (Jan 15) -> gets 150.0
        assert allocs[0] == {"invoice_id": "INV-2", "amount_applied": 150.0}
        # INV-1 is next (Feb 01) -> gets remaining 50.0
        assert allocs[1] == {"invoice_id": "INV-1", "amount_applied": 50.0}

        # Allocation with metadata and unallocated remainder
        allocs_meta, unalloc_meta = allocate_documents_fifo(
            Decimal("500.0"), invoices, id_key="invoice_id", include_metadata=True
        )
        assert unalloc_meta == Decimal("50.0")
        assert len(allocs_meta) == 3
        assert allocs_meta[0]["due_date"] == "2026-01-15"
        assert allocs_meta[0]["balance"] == 150.0

        with pytest.raises(ValueError):
            allocate_documents_fifo(0, invoices)



class TestContactsHelper:
    def test_find_contact_by_gstin(self):
        mock_books = MagicMock()
        mock_books.contacts.list_iter.return_value = [
            {"contact_id": "101", "contact_name": "Vendor Alpha", "gst_no": "33AAAAA0000A1Z5"},
            {
                "contact_id": "102",
                "contact_name": "Vendor Beta",
                "custom_fields": [{"api_name": "gstin", "value": "33BBBBB1111B1Z2"}],
            },
        ]

        # Match direct gst_no
        match1 = find_contact_by_gstin(mock_books, "33aaaaa0000a1z5")
        assert match1 is not None
        assert match1["contact_id"] == "101"

        # Match custom field
        match2 = find_contact_by_gstin(mock_books, "33BBBBB1111B1Z2")
        assert match2 is not None
        assert match2["contact_id"] == "102"

        # No match
        assert find_contact_by_gstin(mock_books, "99UNKNOWN") is None

    def test_find_contact_by_name(self):
        mock_books = MagicMock()
        mock_books.contacts.list.return_value = {
            "contacts": [
                {"contact_id": "201", "contact_name": "Apex Industries", "company_name": "Apex Inc"},
            ]
        }

        # Exact match
        res = find_contact_by_name(mock_books, "apex industries")
        assert res is not None
        assert res["contact_id"] == "201"

        # Search not found
        mock_books.contacts.list.return_value = {"contacts": []}
        assert find_contact_by_name(mock_books, "NonExistent") is None

    def test_fetch_active_customers_map(self):
        mock_books = MagicMock()
        mock_books.contacts.list_all.return_value = [
            {"contact_id": "C101", "contact_name": "Cust 1", "custom_fields": [{"api_name": "ext_id", "value": "E-01"}]},
            {"contact_id": "C102", "contact_name": "Cust 2", "custom_fields": [{"api_name": "ext_id", "value": "E-02"}]},
        ]

        # Keyed by contact_id
        map_by_id = fetch_active_customers_map(mock_books, key_field="contact_id")
        assert "C101" in map_by_id
        assert "C102" in map_by_id

        # Keyed by custom field ext_id
        map_by_ext = fetch_active_customers_map(mock_books, key_field="ext_id")
        assert "E-01" in map_by_ext
        assert "E-02" in map_by_ext
        assert map_by_ext["E-01"]["contact_name"] == "Cust 1"


class TestItemsHelper:
    def test_fetch_items_lookup(self):
        mock_books = MagicMock()
        mock_books.items.list_iter.return_value = [
            {"item_id": "I1", "name": "Item One", "sku": "SKU-001"},
            {"item_id": "I2", "name": "Item Two", "sku": "SKU-002"},
        ]

        lookup = fetch_items_lookup(mock_books, key_field="sku", purchase_account_id="ACC-123")
        assert "SKU-001" in lookup
        assert lookup["SKU-001"]["item_id"] == "I1"
        assert lookup["SKU-002"]["name"] == "Item Two"
        mock_books.items.list_iter.assert_called_once_with(
            params={"status": "active", "purchase_account_id": "ACC-123"},
            resource_key="items",
        )

    def test_fetch_items_by_purchase_account(self):
        mock_books = MagicMock()
        mock_books.items.list_iter.return_value = [
            {"item_id": "I10", "sku": "POLY-01"},
        ]

        lookup = fetch_items_by_purchase_account(mock_books, purchase_account_id="ACC-POLY")
        assert "POLY-01" in lookup
        assert lookup["POLY-01"]["item_id"] == "I10"

        with pytest.raises(ValueError):
            fetch_items_by_purchase_account(mock_books, "")

    def test_find_item_by_sku_or_name(self):
        mock_books = MagicMock()
        mock_books.items.list.return_value = {
            "items": [
                {"item_id": "I1", "item_name": "Copper Cable 2.5mm", "sku": "CAB-COP-2.5"},
            ]
        }

        match = find_item_by_sku_or_name(mock_books, "CAB-COP-2.5", purchase_account_id="ACC-555")
        assert match is not None
        assert match["item_id"] == "I1"
        mock_books.items.list.assert_called_once_with(
            params={"search_text": "CAB-COP-2.5", "purchase_account_id": "ACC-555"}
        )



class TestFilesHelper:
    def test_workdrive_upload_file(self, tmp_path):
        test_file = tmp_path / "sample.pdf"
        test_file.write_text("dummy content")

        mock_wd = MagicMock()
        mock_wd.files.upload.return_value = {"data": [{"id": "wd_file_123"}]}

        res = workdrive_upload_file(mock_wd, "folder_99", str(test_file))
        assert res["data"][0]["id"] == "wd_file_123"
        mock_wd.files.upload.assert_called_once_with(
            folder_id="folder_99",
            file_path=str(test_file),
            file_name="sample.pdf",
        )

    def test_attach_file_to_books_resource(self, tmp_path):
        test_file = tmp_path / "invoice.pdf"
        test_file.write_text("pdf bytes")

        mock_books = MagicMock()
        mock_books.request.return_value = {"code": 0, "message": "The file has been attached."}

        res = attach_file_to_books_resource(
            mock_books,
            resource_name="salesorders",
            resource_id="SO-1001",
            file_path=str(test_file),
        )
        assert res["code"] == 0
        mock_books.request.assert_called_once()
        call_args = mock_books.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "salesorders/SO-1001/attachment"

    def test_workdrive_upload_and_attach(self, tmp_path):
        test_file = tmp_path / "doc.pdf"
        test_file.write_text("content")

        mock_wd = MagicMock()
        mock_wd.files.upload.return_value = {"data": [{"id": "wd_file_999"}]}

        mock_books = MagicMock()
        mock_books.request.return_value = {"code": 0, "message": "Attached"}

        res = workdrive_upload_and_attach(
            mock_wd,
            mock_books,
            folder_id="folder_abc",
            file_path=str(test_file),
            resource_name="invoices",
            resource_id="INV-555",
        )
        assert "workdrive" in res
        assert "books_attachment" in res
