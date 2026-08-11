import unittest
from unittest.mock import patch, MagicMock
from workflows.polycab_credit_memos.processor import (
    parse_polycab_credit_memo,
    resolve_vendor_id,
    resolve_account_id,
    resolve_item_id,
    create_vendor_credit_from_pdf,
    upload_vendor_credit_attachment,
    upload_to_workdrive
)
from workflows.core.config import Config

class TestCreditMemoProcessor(unittest.TestCase):
    @patch("os.path.exists")
    @patch("pdfplumber.open")
    def test_parse_polycab_credit_memo(self, mock_plumber_open, mock_exists):
        mock_exists.return_value = True
        
        # Mock pdfplumber structures
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_plumber_open.return_value.__enter__.return_value = mock_pdf
        mock_pdf.pages = [mock_page]
        
        mock_page.extract_text.return_value = """
        POLYCAB INDIA LIMITED
        Credit Note
        Buyer's details / Place of Supply: Code Customer PO Number : Credit Note No :
        BHARATH DISTRIBUTORS Customer PO Date : Credit Note Date : 03-MAR-26
        Consignee's details / Place of Delivery: AR Invoice Number : 2603211538
        BHARATH DISTRIBUTORS Code Invoice Date : 03-MAR-2026
        Sr. CGST
        HSN/SAC Item Code Description UOM Rate/ Unit Qty Freight Amount Rs. CGST Amnt SGST Rate SGST Amnt Total Value
        1 94054900 LDO0115087 Scintillate Slim Integral LED Downlight 5W 6500K NOS 64.91 1 0 64.91 9.00 5.84 9% 5.84 76.59
        TOTAL 108896.82
        (Rupees One Lakh Eight Thousand Eight Hundred Ninety Six and paise Eighty Two only) For POLYCAB INDIA LIMITED
        """
        
        details = parse_polycab_credit_memo("dummy_memo.pdf")
        
        self.assertEqual(details["vendor_credit_number"], "2603211538")
        self.assertEqual(details["date"], "2026-03-03")
        self.assertEqual(details["amount"], 108896.82)
        self.assertTrue("Scintillate Slim Integral" in details["description"])

    @patch("os.path.exists", return_value=True)
    @patch("pdfplumber.open")
    def test_parse_rejects_pdf_without_extractable_text(self, mock_plumber_open, mock_exists):
        page = MagicMock()
        page.extract_text.return_value = None
        mock_plumber_open.return_value.__enter__.return_value.pages = [page]

        with self.assertRaisesRegex(ValueError, "No extractable text"):
            parse_polycab_credit_memo("image-only.pdf")

    @patch("os.path.exists", return_value=True)
    @patch("pdfplumber.open")
    def test_parse_rejects_unknown_invoice_month(self, mock_plumber_open, mock_exists):
        page = MagicMock()
        page.extract_text.return_value = "Invoice Date : 03-XYZ-2026"
        mock_plumber_open.return_value.__enter__.return_value.pages = [page]

        with self.assertRaisesRegex(ValueError, "Unsupported invoice month"):
            parse_polycab_credit_memo("bad-date.pdf")

    def test_resolve_vendor_id(self):
        books_client = MagicMock()
        books_client.contacts.list.return_value = {
            "contacts": [{"contact_id": "resolved_vendor_999"}]
        }
        
        vendor_id = resolve_vendor_id(books_client, "Polycab")
        self.assertEqual(vendor_id, "resolved_vendor_999")
        books_client.contacts.list.assert_called_once_with(params={"contact_name": "Polycab"})

    def test_resolve_account_id(self):
        books_client = MagicMock()
        books_client.chart_of_accounts.list.return_value = {
            "chartofaccounts": [
                {"account_id": "acc_01", "account_name": "Office Supplies"},
                {"account_id": "acc_02", "account_name": "Polycab Scheme - Expense"}
            ]
        }
        
        account_id = resolve_account_id(books_client, "Polycab Scheme - Expense")
        self.assertEqual(account_id, "acc_02")

    @patch("workflows.polycab_credit_memos.processor.resolve_account_id")
    @patch("workflows.polycab_credit_memos.processor.resolve_bill_id_by_number")
    @patch("workflows.polycab_credit_memos.processor.parse_polycab_credit_memo")
    @patch("workflows.polycab_credit_memos.processor.resolve_vendor_id")
    @patch("workflows.polycab_credit_memos.processor.resolve_item_id")
    def test_create_vendor_credit_from_pdf(
        self,
        mock_resolve_item,
        mock_resolve_vend,
        mock_parse,
        mock_resolve_bill,
        mock_resolve_account,
    ):
        books_client = MagicMock()
        mock_parse.return_value = {
            "vendor_name": "Polycab India Limited",
            "vendor_credit_number": "2603233393",
            "date": "2026-03-31",
            "amount": 810.31,
            "description": "SG/SPECIAL SCHEME",
            "raw_text": "Original Tax Inv. No. : \n"
        }
        mock_resolve_vend.return_value = "vendor_99"
        mock_resolve_item.return_value = "item_123"
        mock_resolve_account.return_value = "account_456"
        books_client.vendor_credits.create.return_value = {
            "vendorcredit": {"vendor_credit_id": "vc_100"}
        }
        
        # Test Case 1: No bill number in PDF (registered type and out of scope tax)
        res = create_vendor_credit_from_pdf(books_client, "dummy.pdf")
        self.assertEqual(res["vendor_credit_id"], "vc_100")
        
        books_client.vendor_credits.create.assert_called_once()
        payload = books_client.vendor_credits.create.call_args.args[0]
        self.assertEqual(payload["vendor_id"], "vendor_99")
        self.assertEqual(payload["location_id"], Config.EXPECTED_LOCATION_ID)
        self.assertEqual(payload["vendor_credit_number"], "2603233393")
        self.assertEqual(payload["reference_invoice_type"], "registered")
        self.assertNotIn("bill_id", payload)
        self.assertEqual(payload["line_items"][0]["item_id"], "item_123")
        self.assertEqual(payload["line_items"][0]["account_id"], "account_456")
        self.assertEqual(payload["line_items"][0]["rate"], 810.31)
        self.assertEqual(payload["line_items"][0]["gst_treatment_code"], "out_of_scope")
        self.assertNotIn("tax_id", payload["line_items"][0])
        
        # Test Case 2: Bill number explicitly in PDF
        books_client.vendor_credits.create.reset_mock()
        mock_parse.return_value["raw_text"] = "Original Tax Inv. No. : BILL999\n"
        mock_resolve_bill.return_value = "bill_777"
        
        res = create_vendor_credit_from_pdf(books_client, "dummy.pdf")
        books_client.vendor_credits.create.assert_called_once()
        mock_resolve_bill.assert_called_once_with(books_client, "vendor_99", "BILL999")
        payload = books_client.vendor_credits.create.call_args.args[0]
        self.assertEqual(payload["bill_id"], "bill_777")
        self.assertNotIn("reference_invoice_type", payload)
        
        # Test Case 3: RSO CN description override with RSO Number alone
        books_client.vendor_credits.create.reset_mock()
        mock_resolve_item.return_value = Config.ZOHO_RSO_CN_ITEM_ID
        mock_parse.return_value["raw_text"] = "RSO Number : 25267008565 E-Way Bill No :\n"
        
        res = create_vendor_credit_from_pdf(books_client, "dummy.pdf")
        books_client.vendor_credits.create.assert_called_once()
        payload = books_client.vendor_credits.create.call_args.args[0]
        self.assertEqual(payload["line_items"][0]["description"], "25267008565")
        self.assertEqual(payload["line_items"][0]["item_id"], Config.ZOHO_RSO_CN_ITEM_ID)

        # Test Case 4: An explicit vendor ID bypasses name-based resolution.
        books_client.vendor_credits.create.reset_mock()
        mock_resolve_vend.reset_mock()
        create_vendor_credit_from_pdf(
            books_client,
            "dummy.pdf",
            vendor_id="vendor_explicit",
            location_id="location_explicit",
        )
        mock_resolve_vend.assert_not_called()
        payload = books_client.vendor_credits.create.call_args.args[0]
        self.assertEqual(payload["vendor_id"], "vendor_explicit")
        self.assertEqual(payload["location_id"], "location_explicit")

    def test_upload_vendor_credit_attachment(self):
        books_client = MagicMock()
        books_client.vendor_credits.add_attachment.return_value = {"status": "success"}
        
        res = upload_vendor_credit_attachment(books_client, "vc_100", "dummy.pdf")
        self.assertEqual(res["status"], "success")
        books_client.vendor_credits.add_attachment.assert_called_once_with("vc_100", "dummy.pdf")

    def test_upload_to_workdrive(self):
        wd_client = MagicMock()
        wd_client.files.upload.return_value = {"data": [{"id": "wd_file_111"}]}
        
        res = upload_to_workdrive(wd_client, "folder_123", "dummy.pdf")
        self.assertEqual(res["data"][0]["id"], "wd_file_111")
        wd_client.files.upload.assert_called_once_with("folder_123", "dummy.pdf")

    def test_resolve_item_id(self):
        # Test Case 1: Scheme CN (RSO Number missing or empty)
        self.assertEqual(resolve_item_id("Some raw text without RSO"), Config.ZOHO_SCHEME_CN_ITEM_ID)
        self.assertEqual(resolve_item_id("RSO Number : \n"), Config.ZOHO_SCHEME_CN_ITEM_ID)
        
        # Test Case 2: RSO CN (RSO Number present and non-empty)
        self.assertEqual(resolve_item_id("RSO Number : 12345"), Config.ZOHO_RSO_CN_ITEM_ID)
        self.assertEqual(resolve_item_id("RSO No. : 25267008565"), Config.ZOHO_RSO_CN_ITEM_ID)
        self.assertEqual(resolve_item_id("RSO No : 98765"), Config.ZOHO_RSO_CN_ITEM_ID)
        
        # Test Case 3: RSO CN based on keywords
        self.assertEqual(resolve_item_id("return type without reference text"), Config.ZOHO_RSO_CN_ITEM_ID)
        self.assertEqual(resolve_item_id("Contains ldo01 item"), Config.ZOHO_RSO_CN_ITEM_ID)
