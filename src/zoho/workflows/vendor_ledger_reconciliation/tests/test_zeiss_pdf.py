import os
import unittest
from unittest.mock import patch, MagicMock
from zoho.workflows.vendor_ledger_reconciliation.zeiss_pdf import (
    parse_month_from_filename,
    format_amount,
    parse_zeiss_pdf_statement,
    consolidate_zeiss_statements
)

class TestZeissPdf(unittest.TestCase):
    def test_parse_month_from_filename(self):
        self.assertEqual(parse_month_from_filename("Dec 2024.pdf"), "December 2024")
        self.assertEqual(parse_month_from_filename("Jan 2025_1.pdf"), "January 2025")
        with self.assertRaises(ValueError):
            parse_month_from_filename("invalid_filename.pdf")
            
    def test_format_amount(self):
        self.assertEqual(format_amount("123.45"), "123.45")
        self.assertEqual(format_amount("123.00"), "123")
        self.assertEqual(format_amount("0.0"), "0")
        self.assertEqual(format_amount("abc"), "abc")
        
    @patch("pdfplumber.open")
    @patch("os.path.exists")
    def test_parse_zeiss_pdf_statement(self, mock_exists, mock_pdf_open):
        mock_exists.return_value = True
        
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_pdf_open.return_value.__enter__.return_value = mock_pdf
        mock_pdf.pages = [mock_page]
        
        mock_text = (
            "Statement details\n"
            "01.12.2024 doc001 inv001 invoice 100.00 0.00 100.00\n"
            "02.12.2024 doc002 inv002 Credit Note 0.00 50.00 50.00\n"
            "03.12.2024 doc003 Receipts 0.00 75.00 -25.00\n"
        )
        mock_page.extract_text.return_value = mock_text
        
        rows = parse_zeiss_pdf_statement("Dec 2024.pdf")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Statement Month"], "December 2024")
        self.assertEqual(rows[0]["Posting Date"], "01.12.2024")
        self.assertEqual(rows[0]["Document No"], "doc001")
        self.assertEqual(rows[0]["Invoice Number"], "inv001")
        self.assertEqual(rows[0]["Voucher Type"], "invoice")
        self.assertEqual(rows[0]["Debit"], "100")
        self.assertEqual(rows[0]["Credit"], "0")
        
        self.assertEqual(rows[1]["Voucher Type"], "Credit Note")
        self.assertEqual(rows[1]["Debit"], "0")
        self.assertEqual(rows[1]["Credit"], "50")

    @patch("zoho.workflows.vendor_ledger_reconciliation.zeiss_pdf.parse_zeiss_pdf_statement")
    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("builtins.open", new_callable=MagicMock)
    def test_consolidate_zeiss_statements(self, mock_open, mock_listdir, mock_isdir, mock_parse):
        mock_isdir.return_value = True
        mock_listdir.return_value = ["Dec 2024.pdf", "Jan 2025.pdf"]
        
        # Mock rows returned by parse_zeiss_pdf_statement
        mock_parse.side_effect = [
            [
                {
                    "Statement Month": "December 2024",
                    "Posting Date": "15.12.2024",
                    "Document No": "doc1",
                    "Invoice Number": "inv1",
                    "Due Date": "15.12.2024",
                    "Voucher Type": "invoice",
                    "Debit": "100.00",
                    "Credit": "0.00",
                    "Closing Balance": "100.00",
                    "Remarks": ""
                }
            ],
            [
                {
                    "Statement Month": "January 2025",
                    "Posting Date": "15.01.2025",
                    "Document No": "doc2",
                    "Invoice Number": "inv2",
                    "Due Date": "15.01.2025",
                    "Voucher Type": "invoice",
                    "Debit": "200.00",
                    "Credit": "0.00",
                    "Closing Balance": "300.00",
                    "Remarks": ""
                }
            ]
        ]
        
        rows = consolidate_zeiss_statements("/dummy/dir", "/dummy/out.csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Document No"], "doc1")
        self.assertEqual(rows[1]["Document No"], "doc2")
        mock_open.assert_called_once()
