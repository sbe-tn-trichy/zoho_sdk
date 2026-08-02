import importlib.util
import unittest

import workflows


class TestWorkflowsPackage(unittest.TestCase):
    def test_top_level_package_exports_workflows(self):
        self.assertTrue(callable(workflows.process_polycab_credit_memos))
        self.assertTrue(callable(workflows.reconcile_vendor))

    def test_removed_legacy_package_is_not_available(self):
        self.assertIsNone(importlib.util.find_spec("zoho_sdk_advanced"))


if __name__ == "__main__":
    unittest.main()
