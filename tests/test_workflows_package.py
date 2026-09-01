import importlib.util
import unittest

import workflows
from workflows.bank_reconciliation import match_ledger_entries as legacy_match
from workflows.bank_vendor_ledger_matching import match_ledger_entries
from workflows.polycab_credit_memos import process_polycab_credit_memos
from workflows.vendor_ledger_reconciliation import reconcile_vendor_account


class TestWorkflowsPackage(unittest.TestCase):
    def test_top_level_package_exports_workflows(self):
        self.assertTrue(callable(workflows.process_polycab_credit_memos))
        self.assertTrue(callable(workflows.reconcile_vendor))

    def test_removed_legacy_package_is_not_available(self):
        self.assertIsNone(importlib.util.find_spec("zoho_sdk_advanced"))

    def test_bank_vendor_ledger_matching_is_canonical_with_legacy_alias(self):
        self.assertIs(workflows.match_ledger_entries, match_ledger_entries)
        self.assertIs(legacy_match, match_ledger_entries)

    def test_workflow_subpackages_export_supported_apis(self):
        self.assertIs(workflows.process_polycab_credit_memos, process_polycab_credit_memos)
        self.assertIs(workflows.reconcile_vendor_account, reconcile_vendor_account)


if __name__ == "__main__":
    unittest.main()
