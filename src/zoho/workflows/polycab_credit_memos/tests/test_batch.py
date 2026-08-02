import unittest
from unittest.mock import patch, MagicMock
from zoho.workflows.polycab_credit_memos.processor import (
    process_polycab_credit_memos,
    check_vendor_credits_location
)

class TestCreditMemoBatch(unittest.TestCase):
    @patch("zoho.workflows.polycab_credit_memos.processor.upload_to_workdrive")
    @patch("zoho.workflows.polycab_credit_memos.processor.upload_vendor_credit_attachment")
    @patch("zoho.workflows.polycab_credit_memos.processor.create_vendor_credit_from_pdf")
    @patch("zoho.workflows.polycab_credit_memos.processor.parse_polycab_credit_memo")
    @patch("zoho.workflows.polycab_credit_memos.processor.fetch_vendor_credits")
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_process_polycab_credit_memos(
        self, mock_listdir, mock_exists, mock_fetch, mock_parse, mock_create, mock_attach, mock_upload
    ):
        mock_exists.return_value = True
        mock_listdir.return_value = ["CM-2603211538.pdf", "CN-2603211539.pdf"]
        
        # Mock fetch_vendor_credits returning one existing credit
        mock_fetch.return_value = [
            {"vendor_credit_number": "2603211538", "vendor_credit_id": "vc_111"}
        ]
        
        # Mock WorkDrive list_all_files returning one existing file
        wd_client = MagicMock()
        wd_client.files.list_all_files.return_value = [
            {"attributes": {"name": "CM-2603211538.pdf"}}
        ]
        
        # Mock parse_polycab_credit_memo details
        mock_parse.side_effect = [
            {"vendor_credit_number": "2603211538", "amount": 100.0, "date": "2026-03-03", "description": "existing", "raw_text": ""},
            {"vendor_credit_number": "2603211539", "amount": 200.0, "date": "2026-03-04", "description": "new", "raw_text": ""}
        ]
        
        # Mock create vendor credit returning new credit
        mock_create.return_value = {"vendor_credit_id": "vc_222"}
        
        books_client = MagicMock()
        
        summary = process_polycab_credit_memos(
            books_client=books_client,
            wd_client=wd_client,
            files_dir="/dummy/cn",
            folder_id="folder_123",
            vendor_id="vendor_999"
        )
        
        self.assertEqual(summary["total_files"], 2)
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["books_created"], 1) # CM-2603211538 is skipped (exists)
        self.assertEqual(summary["books_skipped"], 1)
        self.assertEqual(summary["wd_uploaded"], 1) # CM-2603211538 is skipped (exists in WD)
        self.assertEqual(summary["wd_skipped"], 1)
        
        # Verify calls
        mock_create.assert_called_once()
        mock_upload.assert_called_once()
        import os
        expected_path = os.path.join("/dummy/cn", "CN-2603211539.pdf")
        mock_attach.assert_called_with(books_client, "vc_222", expected_path)

        
    def test_check_vendor_credits_location(self):
        books_client = MagicMock()
        
        # Mock the typed SDK Vendor Credits resource.
        books_client.vendor_credits.list_all.return_value = [
            {
                "vendor_credit_id": "vc_1",
                "vendor_credit_number": "VC1",
                "location_id": "loc_expected",
                "location_name": "Expected Location",
                "total": 100.0,
                "date": "2026-01-01",
                "status": "open",
            },
            {
                "vendor_credit_id": "vc_2",
                "vendor_credit_number": "VC2",
                "location_id": "loc_other",
                "location_name": "Other Location",
                "total": 200.0,
                "date": "2026-01-02",
                "status": "open",
            },
            {
                "vendor_credit_id": "vc_3",
                "vendor_credit_number": "VC3",
                "total": 300.0,
                "date": "2026-01-03",
                "status": "open",
            },
        ]
        
        results = check_vendor_credits_location(
            books_client=books_client,
            vendor_id="vendor_999",
            expected_location_id="loc_expected"
        )
        
        self.assertEqual(len(results["correct"]), 1)
        self.assertEqual(len(results["mismatched"]), 1)
        self.assertEqual(len(results["no_location"]), 1)
        self.assertEqual(results["total_checked"], 3)
        self.assertEqual(results["correct"][0]["id"], "vc_1")
        self.assertEqual(results["mismatched"][0]["id"], "vc_2")
        self.assertEqual(results["no_location"][0]["id"], "vc_3")
