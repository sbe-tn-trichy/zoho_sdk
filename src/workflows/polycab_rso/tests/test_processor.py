from unittest.mock import MagicMock, call, patch

import pytest

from workflows.polycab_rso.processor import (
    import_polycab_rso_pdf,
    parse_polycab_rso_pdf,
)


EXTRACTED_RSO = """
POLYCAB INDIA LIMITED
Sales Order
Customer Name : BHARATH DISTRIBUTORS - 109461 Sales Order Number : 262707003493
SO Entered Date : 04-AUG-26
SO Booked Date : 10-AUG-26
Order Type : RMA-WO-REF
ITEM DETAILS
1 FPENSST008P 18X450MM BLACK SILVER NUMBERS 2 T.B.PD 0.00 0.00 4004.01 Yes 8008.02
2 FTANSST033P X SKY BLUE NUMBERS 1 T.B.PD 0.00 0.00 1703.75 Yes 1703.75
Total Rs. 9711.77
CGST_RETURN_WO 9 % 874.06
SGST_RETURN_WO 9 % 874.06
Grand Total 11459.89
LINE DETAILS
1 FPENSST008P 18X450MM NUMBERS 2 T.B.PD 0.00 0.00 4004.01 Yes 8008.02
2 FTANSST033P X NUMBERS 1 T.B.PD 0.00 0.00 1703.75 Yes 1703.75
"""


@patch("workflows.polycab_rso.processor.os.path.isfile", return_value=True)
@patch("workflows.polycab_rso.processor.pdfplumber.open")
def test_parser_stops_at_total_and_ignores_repeated_table(mock_open, mock_isfile):
    page = MagicMock()
    page.extract_text.return_value = EXTRACTED_RSO
    mock_open.return_value.__enter__.return_value.pages = [page]

    parsed = parse_polycab_rso_pdf("RSO_262707003493.pdf")

    assert parsed["sales_order_number"] == "262707003493"
    assert parsed["customer_name"] == "BHARATH DISTRIBUTORS"
    assert parsed["customer_code"] == "109461"
    assert parsed["date"] == "2026-08-04"
    assert parsed["booked_date"] == "2026-08-10"
    assert parsed["order_type"] == "RMA-WO-REF"
    assert parsed["subtotal"] == 9711.77
    assert parsed["grand_total"] == 11459.89
    assert [item["sku"] for item in parsed["items"]] == [
        "FPENSST008P",
        "FTANSST033P",
    ]


@patch("workflows.polycab_rso.processor.parse_polycab_rso_pdf")
def test_import_creates_sales_order_in_location_and_attaches_pdf(mock_parse):
    mock_parse.return_value = {
        "sales_order_number": "262707003493",
        "customer_name": "BHARATH DISTRIBUTORS",
        "customer_code": "109461",
        "date": "2026-08-04",
        "booked_date": "2026-08-10",
        "order_type": "RMA-WO-REF",
        "subtotal": 9711.77,
        "grand_total": 11459.89,
        "items": [
            {"sequence": 1, "sku": "SKU1", "quantity": 2.0, "rate": 10.0, "amount": 20.0},
            {"sequence": 2, "sku": "SKU2", "quantity": 1.0, "rate": 5.0, "amount": 5.0},
        ],
    }
    books = MagicMock()
    books.sales_orders.list_all.return_value = []
    books.items.list.side_effect = [
        {"items": [{"item_id": "item1", "sku": "SKU1"}]},
        {"items": [{"item_id": "item2", "sku": "SKU2"}]},
    ]
    books.sales_orders.create.return_value = {
        "salesorder": {"salesorder_id": "so1", "salesorder_number": "262707003493"}
    }

    result = import_polycab_rso_pdf(
        books,
        "RSO_262707003493.pdf",
        customer_id="customer1",
        location_id="sri-bharath-location",
    )

    assert result["created"] is True
    payload = books.sales_orders.create.call_args.args[0]
    assert payload["customer_id"] == "customer1"
    assert payload["location_id"] == "sri-bharath-location"
    assert payload["salesorder_number"] == "262707003493"
    assert payload["reference_number"] == "262707003493"
    assert payload["line_items"] == [
        {"item_id": "item1", "quantity": 2.0, "rate": 10.0},
        {"item_id": "item2", "quantity": 1.0, "rate": 5.0},
    ]
    books.sales_orders.add_attachment.assert_called_once_with(
        "so1", "RSO_262707003493.pdf"
    )


@patch("workflows.polycab_rso.processor.parse_polycab_rso_pdf")
def test_import_existing_order_only_adds_missing_attachment(mock_parse):
    mock_parse.return_value = {"sales_order_number": "262707003493"}
    books = MagicMock()
    books.sales_orders.list_all.return_value = [
        {
            "salesorder_id": "so-existing",
            "salesorder_number": "262707003493",
            "has_attachment": False,
        }
    ]

    result = import_polycab_rso_pdf(books, "RSO_262707003493.pdf")

    assert result["created"] is False
    assert result["attachment_uploaded"] is True
    books.sales_orders.create.assert_not_called()
    books.items.list.assert_not_called()
    books.sales_orders.add_attachment.assert_called_once_with(
        "so-existing", "RSO_262707003493.pdf"
    )


@patch("workflows.polycab_rso.processor.parse_polycab_rso_pdf")
def test_import_refuses_to_create_when_sku_is_missing(mock_parse):
    mock_parse.return_value = {
        "sales_order_number": "262707003493",
        "items": [
            {"sequence": 1, "sku": "MISSING", "quantity": 1.0, "rate": 5.0, "amount": 5.0}
        ],
    }
    books = MagicMock()
    books.sales_orders.list_all.return_value = []
    books.items.list.return_value = {"items": []}

    with pytest.raises(ValueError, match="MISSING"):
        import_polycab_rso_pdf(books, "RSO_262707003493.pdf")

    books.sales_orders.create.assert_not_called()


@patch("workflows.polycab_rso.processor.parse_polycab_rso_pdf")
def test_import_resolves_compact_polycab_code_to_books_sku(mock_parse):
    mock_parse.return_value = {
        "sales_order_number": "262707003493",
        "customer_name": "BHARATH DISTRIBUTORS",
        "customer_code": "109461",
        "date": "2026-08-04",
        "booked_date": "2026-08-10",
        "order_type": "RMA-WO-REF",
        "items": [
            {
                "sequence": 1,
                "sku": "FPENSST008P",
                "quantity": 2.0,
                "rate": 4004.01,
                "amount": 8008.02,
            }
        ],
    }
    books = MagicMock()
    books.sales_orders.list_all.return_value = []
    books.items.list.side_effect = [
        {"items": []},
        {
            "items": [
                {
                    "item_id": "item1",
                    "sku": "FPENSS-T008P",
                    "status": "active",
                }
            ]
        },
    ]
    books.sales_orders.create.return_value = {
        "salesorder": {"salesorder_id": "so1"}
    }

    import_polycab_rso_pdf(books, "RSO_262707003493.pdf")

    assert books.items.list.call_args_list == [
        call(params={"sku": "FPENSST008P"}),
        call(params={"sku": "FPENSS-T008P"}),
    ]
    assert books.sales_orders.create.call_args.args[0]["line_items"] == [
        {"item_id": "item1", "quantity": 2.0, "rate": 4004.01}
    ]


@patch("workflows.polycab_rso.processor.parse_polycab_rso_pdf")
def test_import_uses_approved_sku_replacement(mock_parse):
    mock_parse.return_value = {
        "sales_order_number": "262707003493",
        "customer_name": "BHARATH DISTRIBUTORS",
        "customer_code": "109461",
        "date": "2026-08-04",
        "booked_date": "2026-08-10",
        "order_type": "RMA-WO-REF",
        "items": [
            {
                "sequence": 1,
                "sku": "FCEECST303M",
                "quantity": 1.0,
                "rate": 1922.80,
                "amount": 1922.80,
            }
        ],
    }
    books = MagicMock()
    books.sales_orders.list_all.return_value = []
    books.items.list.return_value = {
        "items": [
            {
                "item_id": "replacement-item",
                "sku": "FCEECS-T187M",
                "status": "active",
            }
        ]
    }
    books.sales_orders.create.return_value = {
        "salesorder": {"salesorder_id": "so1"}
    }

    import_polycab_rso_pdf(books, "RSO_262707003493.pdf")

    books.items.list.assert_called_once_with(params={"sku": "FCEECS-T187M"})
    assert books.sales_orders.create.call_args.args[0]["line_items"] == [
        {"item_id": "replacement-item", "quantity": 1.0, "rate": 1922.8}
    ]
