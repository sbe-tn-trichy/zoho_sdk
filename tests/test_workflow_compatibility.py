import importlib
import unittest

import zoho.workflows
import zoho_sdk_advanced


class TestWorkflowCompatibility(unittest.TestCase):
    def test_root_exports_match(self):
        self.assertIs(
            zoho_sdk_advanced.process_polycab_credit_memos,
            zoho.workflows.process_polycab_credit_memos,
        )

    def test_legacy_subpackage_import(self):
        legacy = importlib.import_module(
            "zoho_sdk_advanced.vendor_ledger_reconciliation"
        )
        current = importlib.import_module(
            "zoho.workflows.vendor_ledger_reconciliation"
        )
        self.assertIs(legacy, current)


if __name__ == "__main__":
    unittest.main()
