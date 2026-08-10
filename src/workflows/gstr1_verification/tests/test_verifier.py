import unittest
from datetime import date
from unittest.mock import MagicMock

from workflows.gstr1_verification import (
    GSTR1VerificationConfig,
    GSTR1Verifier,
    verify_gstr1,
)


def invoice(
    number,
    invoice_date,
    status="sent",
    invoice_id=None,
    einvoice_details=None,
    location_id=None,
):
    result = {
        "invoice_id": invoice_id or number,
        "invoice_number": number,
        "date": invoice_date,
        "status": status,
        "customer_name": "Customer",
        "total": 100,
        "location_id": location_id,
    }
    if einvoice_details is not None:
        result["einvoice_details"] = einvoice_details
    return result


def credit_note(
    number,
    document_date,
    status="open",
    creditnote_id=None,
    einvoice_details=None,
    location_id=None,
):
    result = {
        "creditnote_id": creditnote_id or number,
        "creditnote_number": number,
        "date": document_date,
        "status": status,
        "customer_name": "Customer",
        "total": 20,
        "location_id": location_id,
    }
    if einvoice_details is not None:
        result["einvoice_details"] = einvoice_details
    return result


class TestGSTR1Verifier(unittest.TestCase):
    def make_client(self, target_invoices=None, target_credit_notes=None,
                    sequence_invoices=None, sequence_credit_notes=None):
        client = MagicMock()
        client.invoices.list_all.side_effect = [
            list(target_invoices or []),
            list(sequence_invoices if sequence_invoices is not None else target_invoices or []),
        ]
        client.credit_notes.list_all.side_effect = [
            list(target_credit_notes or []),
            list(sequence_credit_notes if sequence_credit_notes is not None else target_credit_notes or []),
        ]
        client.locations.list_all.return_value = []
        return client

    def test_defaults_to_previous_calendar_month_across_year_boundary(self):
        client = self.make_client()
        report = verify_gstr1(
            client,
            as_of=date(2026, 1, 10),
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertEqual(report["period"]["month"], "2025-12")
        self.assertEqual(report["period"]["start_date"], "2025-12-01")
        self.assertEqual(report["period"]["end_date"], "2025-12-31")
        self.assertEqual(report["period"]["sequence_scope_start"], "2025-04-01")
        self.assertTrue(report["overall_passed"])
        client.invoices.list_all.assert_any_call(
            params={"date_start": "2025-12-01", "date_end": "2025-12-31"}
        )

    def test_reports_drafts_missing_numbers_and_backdated_sequence(self):
        documents = [
            invoice("INV-001", "2026-07-05", "draft"),
            invoice("INV-003", "2026-07-04"),
        ]
        client = self.make_client(target_invoices=documents)

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertFalse(report["overall_passed"])
        self.assertEqual(report["checks"]["draft_documents"]["count"], 1)
        sequence = report["checks"]["number_sequence"]
        self.assertEqual([item["number"] for item in sequence["missing"]], ["INV-002"])
        self.assertEqual(sequence["out_of_chronology"][0]["number"], "INV-003")

    def test_financial_year_population_prevents_false_gap_but_exposes_backdating(self):
        target = [
            invoice("INV-100", "2026-07-01"),
            invoice("INV-102", "2026-07-02"),
        ]
        universe = target + [invoice("INV-101", "2026-06-30")]
        client = self.make_client(target_invoices=target, sequence_invoices=universe)

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertEqual(report["checks"]["number_sequence"]["missing"], [])
        self.assertEqual(
            report["checks"]["number_sequence"]["out_of_chronology"][0]["number"],
            "INV-101",
        )

    def test_sequence_reports_duplicates_unparseable_numbers_and_width_changes(self):
        target = [
            invoice("INV-01", "2026-07-01", invoice_id="a"),
            invoice("INV-01", "2026-07-01", invoice_id="b"),
            invoice("INV-002", "2026-07-02", invoice_id="c"),
            invoice("MANUAL", "2026-07-03", invoice_id="d"),
        ]
        client = self.make_client(target_invoices=target)

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        sequence = report["checks"]["number_sequence"]
        self.assertEqual(len(sequence["duplicates"]), 1)
        self.assertEqual(len(sequence["unparseable_numbers"]), 1)
        self.assertEqual(sequence["inconsistent_width"][0]["widths"], [2, 3])
        self.assertFalse(sequence["passed"])

    def test_sequence_reports_gap_at_month_boundary(self):
        target = [invoice("INV-102", "2026-07-01")]
        universe = [
            invoice("INV-100", "2026-06-30"),
            target[0],
            invoice("INV-104", "2026-08-01"),
        ]
        client = self.make_client(target_invoices=target, sequence_invoices=universe)

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertEqual(
            [item["number"] for item in report["checks"]["number_sequence"]["missing"]],
            ["INV-101", "INV-103"],
        )

    def test_checks_sequences_independently_by_gst_registration(self):
        target = [
            invoice("INV-001", "2026-07-01", invoice_id="a", location_id="loc-a"),
            invoice("INV-003", "2026-07-03", invoice_id="b", location_id="loc-b"),
            invoice("INV-001", "2026-07-02", invoice_id="c", location_id="loc-c"),
        ]
        client = self.make_client(target_invoices=target)
        client.locations.list_all.return_value = [
            {"location_id": "loc-a", "location_name": "A", "tax_settings_id": "gst-1"},
            {"location_id": "loc-b", "location_name": "B", "tax_settings_id": "gst-1"},
            {"location_id": "loc-c", "location_name": "C", "tax_settings_id": "gst-2"},
        ]

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertEqual(set(report["gst_registrations"]), {"gst-1", "gst-2"})
        gst_1 = report["gst_registrations"]["gst-1"]
        gst_2 = report["gst_registrations"]["gst-2"]
        self.assertEqual(
            [item["number"] for item in gst_1["checks"]["number_sequence"]["missing"]],
            ["INV-002"],
        )
        self.assertEqual(gst_2["checks"]["number_sequence"]["duplicates"], [])
        self.assertEqual(
            {item["location_id"] for item in gst_1["locations"]},
            {"loc-a", "loc-b"},
        )

    def test_location_metadata_failure_does_not_club_unknown_locations(self):
        target = [
            invoice("INV-001", "2026-07-01", invoice_id="a", location_id="loc-a"),
            invoice("INV-001", "2026-07-01", invoice_id="b", location_id="loc-b"),
        ]
        client = self.make_client(target_invoices=target)
        client.locations.list_all.side_effect = RuntimeError("locations unavailable")

        report = verify_gstr1(
            client,
            month="2026-07",
            config=GSTR1VerificationConfig(e_invoice_applicable=False),
        )

        self.assertFalse(report["complete"])
        self.assertEqual(
            set(report["gst_registrations"]),
            {"location:loc-a", "location:loc-b"},
        )
        self.assertEqual(report["checks"]["number_sequence"]["duplicates"], [])
        self.assertEqual(report["fetch_errors"][0]["source"], "locations")

    def test_checks_applicable_einvoice_status_and_registration_reference(self):
        target = [
            invoice(
                "INV-001", "2026-07-01", invoice_id="1",
                einvoice_details={"status": "pushed", "inv_ref_num": "IRN-1"},
            ),
            invoice(
                "INV-002", "2026-07-02", invoice_id="2",
                einvoice_details={"status": "yet_to_be_pushed", "inv_ref_num": ""},
            ),
            invoice(
                "INV-003", "2026-07-03", invoice_id="3",
                einvoice_details={"status": "pushed", "inv_ref_num": ""},
            ),
            invoice("INV-004", "2026-07-04", invoice_id="4"),
        ]
        notes = [
            credit_note(
                "CN-001", "2026-07-05", creditnote_id="cn1",
                einvoice_details={
                    "status": "manually_pushed", "inv_ref_num": "IRN-CN-1"
                },
            )
        ]
        client = self.make_client(target_invoices=target, target_credit_notes=notes)

        report = verify_gstr1(client, month="2026-07")

        check = report["checks"]["einvoice_push"]
        self.assertEqual(check["applicable_count"], 4)
        self.assertEqual(len(check["pushed"]), 2)
        self.assertEqual(
            [item["classification"] for item in check["exceptions"]],
            ["not_pushed", "pushed"],
        )
        self.assertEqual([item["number"] for item in check["not_applicable_or_not_returned"]], ["INV-004"])
        self.assertFalse(check["passed"])

    def test_failed_transaction_fetch_makes_report_incomplete(self):
        client = self.make_client(target_invoices=[invoice("INV-001", "2026-07-01")])
        client.invoices.list_all.side_effect = [RuntimeError("API unavailable"), []]

        report = verify_gstr1(client, month="2026-07")

        self.assertFalse(report["complete"])
        self.assertFalse(report["overall_passed"])
        self.assertEqual(report["fetch_errors"][0]["source"], "invoices")

    def test_rejects_invalid_month_and_fiscal_year_setting(self):
        client = self.make_client()
        with self.assertRaisesRegex(ValueError, "expected YYYY-MM"):
            GSTR1Verifier(client).run(month="July 2026")
        with self.assertRaisesRegex(ValueError, "between 1 and 12"):
            GSTR1VerificationConfig(fiscal_year_start_month=13)

if __name__ == "__main__":
    unittest.main()
