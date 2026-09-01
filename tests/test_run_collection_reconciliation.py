import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.run_collection_reconciliation import run_collection_reconciliation


class TestRunCollectionReconciliation(unittest.TestCase):
    @patch("workflows.collection_reconciliation.CollectionReconciler.validate_schema")
    def test_run_collection_reconciliation_single_step(self, mock_validate_schema):
        mock_creator = MagicMock()
        mock_books = MagicMock()
        mock_analytics = MagicMock()

        # Return mock records for creator and books
        mock_creator.list_all_records.return_value = []
        mock_books.bank_transactions.list_all.return_value = []
        mock_validate_schema.return_value = {"valid": True}

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "summary.json"
            result = run_collection_reconciliation(
                bank_account_id="bank-101",
                creator_app_link_name="test-app",
                dry_run=True,
                output_path=out_path,
                creator_client=mock_creator,
                books_client=mock_books,
                analytics_client=mock_analytics,
            )

            self.assertTrue(result["dry_run"])
            self.assertEqual(result["config"]["bank_account_id"], "bank-101")
            self.assertTrue(out_path.exists())

            saved_content = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_content["config"]["bank_account_id"], "bank-101")


if __name__ == "__main__":
    unittest.main()
