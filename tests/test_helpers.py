"""Unit tests for zoho.helpers modules."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from zoho.helpers import (
    GSTIN_PATTERN,
    attach_file_to_books_resource,
    ensure_books_custom_fields,
    extract_custom_fields_dict,
    fetch_active_customers_map,
    fetch_bank_accounts_map,
    fetch_items_lookup,
    find_bank_account_by_name,
    find_contact_by_gstin,
    find_contact_by_name,
    find_item_by_sku_or_name,
    find_transaction_by_number,
    get_custom_field_value,
    get_month_range,
    get_previous_month_range,
    group_contacts_by_gstin,
    is_valid_gstin,
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

        lookup = fetch_items_lookup(mock_books, key_field="sku")
        assert "SKU-001" in lookup
        assert lookup["SKU-001"]["item_id"] == "I1"
        assert lookup["SKU-002"]["name"] == "Item Two"

    def test_find_item_by_sku_or_name(self):
        mock_books = MagicMock()
        mock_books.items.list.return_value = {
            "items": [
                {"item_id": "I1", "item_name": "Copper Cable 2.5mm", "sku": "CAB-COP-2.5"},
            ]
        }

        match = find_item_by_sku_or_name(mock_books, "CAB-COP-2.5")
        assert match is not None
        assert match["item_id"] == "I1"


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
