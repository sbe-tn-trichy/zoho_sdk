import subprocess
import sys
import unittest


class TestPackageImports(unittest.TestCase):
    def test_root_import_does_not_load_workflow_dependencies(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys, zoho; "
                    "assert 'workflows' not in sys.modules; "
                    "assert 'pdfplumber' not in sys.modules; "
                    "assert 'pandas' not in sys.modules"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
