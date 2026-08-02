import unittest
from unittest.mock import patch, MagicMock
import xlrd
from zoho.workflows.vendor_ledger_reconciliation.cleaner import clean_ledger_file

class TestLedgerCleaner(unittest.TestCase):
    @patch("os.path.exists")
    @patch("xlrd.open_workbook")
    def test_clean_ledger_file_mock(self, mock_open_workbook, mock_exists):
        mock_exists.return_value = True
        # Setup mock sheet and workbook
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_open_workbook.return_value = mock_wb
        mock_wb.sheet_by_index.return_value = mock_sheet
        mock_wb.datemode = 0
        
        # Define mock rows
        mock_rows = [
            # Metadata rows
            ["Start Date", ":", "2026-01-01", "", ""],
            ["Party Name", ":", "BHARATH DISTRIBUTORS", "", ""],
            ["", "", "", "", ""],
            # Header row (index 3)
            ["Account No", "Account Name", "AR Invoice Date", "Document Type", "Transaction No", "Transaction Reference", "Customer PO No.", "Debit Amount", "Credit Amount", "Closing Balance"],
            # Valid Row 1
            ["109461", "FAN-BHARATH DISTRIBUTORS", "2026-01-02", "Sales Invoice", "2601238365", "TN721S2526104838", "3112", 314189.27, 0.0, -40884.44],
            # Valid Row 2 (with float transaction number and account number)
            [108738.0, "LTG-BHARATH DISTRIBUTORS", "2026-01-03", "Receipt", "NBJ4RH6RTKHVQZTP", "", "", 0.0, 541000.0, -109972.46],
            # Empty Row (to be skipped)
            ["", "", "", "", "", "", "", "", "", ""],
            # Summary row (to be skipped)
            ["", "", "", "", "", "", "Opening Balance", "Total Debit Amount", "Total Credit Amount", "Closing Balance"],
            ["", "", "", "", "", "", -355073.71, 4851278.47, 4653020.28, -156815.52]
        ]
        
        mock_sheet.nrows = len(mock_rows)
        mock_sheet.ncols = len(mock_rows[3])
        
        def mock_cell_value(row, col):
            return mock_rows[row][col]
            
        def mock_cell(row, col):
            cell = MagicMock()
            cell.value = mock_rows[row][col]
            if isinstance(cell.value, float):
                cell.ctype = xlrd.XL_CELL_NUMBER
            else:
                cell.ctype = xlrd.XL_CELL_TEXT
            return cell
            
        mock_sheet.cell_value.side_effect = mock_cell_value
        mock_sheet.cell.side_effect = mock_cell
        
        # Run cleaner with auto-detection of Polycab key (via filename starting with 277498)
        txs = clean_ledger_file("277498_dummy_path.xls")
        
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[0]["account_no"], "109461")
        self.assertEqual(txs[0]["date"], "2026-01-02")
        self.assertEqual(txs[0]["debit_amount"], 314189.27)
        
        # Verify custom vendor key override works
        txs_explicit = clean_ledger_file("any_name.xls", vendor_key="polycab")
        self.assertEqual(len(txs_explicit), 2)
        
        # Verify unsupported vendor key raises error
        with self.assertRaises(NotImplementedError):
            clean_ledger_file("any_name.xls", vendor_key="unknown")
            
        # Verify unknown file prefix raising auto-detect error
        with self.assertRaises(ValueError):
            clean_ledger_file("some_unknown_ledger.xls")


    @patch("os.path.exists")
    @patch("xlrd.open_workbook")
    def test_get_ledger_metadata_mock(self, mock_open_workbook, mock_exists):
        mock_exists.return_value = True
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_open_workbook.return_value = mock_wb
        mock_wb.sheet_by_index.return_value = mock_sheet
        
        mock_rows = [
            ["Start Date", ":", "2026-01-01"],
            ["End Date", ":", "2026-03-31"],
            ["Party Name", ":", "POLYCAB INDIA LIMITED"],
            ["Opening Balance", ":", -12345.50]
        ]
        mock_sheet.nrows = len(mock_rows)
        mock_sheet.ncols = 3
        mock_sheet.cell_value.side_effect = lambda r, c: mock_rows[r][c]
        
        from zoho.workflows.vendor_ledger_reconciliation.cleaner import get_ledger_metadata
        metadata = get_ledger_metadata("dummy_path.xls")
        
        self.assertEqual(metadata["start_date"], "2026-01-01")
        self.assertEqual(metadata["end_date"], "2026-03-31")
        self.assertEqual(metadata["party_name"], "POLYCAB INDIA LIMITED")
        self.assertEqual(metadata["opening_balance"], -12345.50)
