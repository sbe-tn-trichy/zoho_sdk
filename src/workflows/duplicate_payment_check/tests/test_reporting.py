import unittest

from workflows.duplicate_payment_check import render_html_report, render_markdown_report


class TestDuplicatePaymentHtmlReport(unittest.TestCase):
    def test_renders_summary_rows_and_escapes_values(self):
        payload = {
            "checked_at": "2026-08-17T12:00:00+00:00",
            "organization_id": "org-1",
            "result": {
                "payments_scanned": 10,
                "duplicate_group_count": 1,
                "duplicate_payment_count": 2,
                "skipped": [],
                "duplicate_groups": [{
                    "customer_id": "c1",
                    "customer_name": "A & B <Trading>",
                    "date": "2026-08-01",
                    "amount": "100.00",
                    "payment_count": 2,
                    "payments": [
                        {"payment_id": "p1", "payment_number": "1", "reference_number": "R1", "payment_mode": "Cash"},
                        {"payment_id": "p2", "payment_number": "2", "reference_number": "R2", "payment_mode": "Cash"},
                    ],
                }],
            },
        }

        html = render_html_report(payload)

        self.assertIn("Potential duplicate groups", html)
        self.assertIn("A &amp; B &lt;Trading&gt;", html)
        self.assertEqual(html.count('data-search="'), 2)
        self.assertNotIn("A & B <Trading>", html)

    def test_renders_compact_customer_date_groups(self):
        payload = {
            "result": {
                "payments_scanned": 2,
                "duplicate_group_count": 1,
                "duplicate_payment_count": 2,
                "duplicate_groups": [{
                    "customer_id": "c1",
                    "customer_name": "Acme",
                    "date": "2026-08-01",
                    "amount": "100",
                    "payments": [
                        {"reference_number": "REF-1", "amount": 100},
                        {"reference_number": "", "amount": 100},
                    ],
                }],
            },
        }

        report = render_markdown_report(payload)

        self.assertIn("## Acme, 2026-08-01", report)
        self.assertIn("- REF-1, 100.00", report)
        self.assertIn("- No reference, 100.00", report)


if __name__ == "__main__":
    unittest.main()
