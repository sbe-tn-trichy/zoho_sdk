from __future__ import annotations
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from workflows.ais_reconciliation import (
    CollectionConfig, collect_books_snapshot, read_snapshot, reconcile_ais, write_report,
)
from workflows.ais_reconciliation.master import validate_master

GSTIN = "33ABCDE1234F1Z5"
PAN = "ABCDE1234F"


@pytest.fixture
def master():
    def rows(headers, data):
        return [{"row": 1, "cells": headers}] + [{"row": i + 2, "cells": c} for i, c in enumerate(data)]
    return {
        "24-25 GST purchases": rows({"B": "Source / supplier", "E": "GSTIN", "F": "Return period", "G": "Purchase", "H": "Status"},
            [{"A": "EXC-GSTR1(P)", "B": f"Vendor ({PAN})", "C": 1, "D": 1, "E": GSTIN, "F": "APR-2024", "G": 100, "H": "Active", "I": ""}]),
        "24-25 GST sales": rows({"E": "GSTIN", "F": "Return period", "G": "Total turnover", "H": "Taxable turnover", "I": "Status"},
            [{"E": GSTIN, "F": "APR-2024", "G": 100, "H": 100, "I": "Active"}]),
        "24-25 TDS TCS": rows({"B": "Code", "G": "Payment date", "H": "Amount", "L": "Status"}, []),
        "24-25 Source totals": rows({"A": "Group", "F": "Reported amount"},
            [{"A": "GST purchases", "F": 100}, {"A": "GST turnover", "F": 100}]),
        "Tax payments": rows({}, []), "Refunds": rows({}, []),
    }


@pytest.fixture
def snapshot():
    return {"metadata": {"version": 1, "organization_id": "org", "from_date": "2024-04-01",
                         "to_date": "2025-03-31", "captured_at": "2026-10-02", "complete": True, "requests": 0},
            "data": {
                "organization": {"organization": {"organization_id": "org"}},
                "locations": [{"location_id": "root", "location_name": "Root", "tax_reg_no": GSTIN}],
                "contacts": [{"contact_id": "vendor", "contact_name": "Vendor", "pan_no": PAN, "gst_no": GSTIN}],
                "accounts": [{"account_id": "gst", "account_name": "Input CGST", "account_type": "other_current_asset"}],
                "bills": [{"bill_id": "b", "bill_number": "B1", "date": "2024-04-15", "total": 118,
                           "status": "paid", "vendor_id": "vendor", "vendor_name": "Vendor",
                           "gst_no": GSTIN, "location_id": "root", "location_name": "Root", "entity_type": "bill"}],
                "vendor_credits": [], "expenses": [], "bank_windows": [], "tax_income_ledger": [],
                "input_tax_ledger": [{"transaction_type": "bill", "transaction_id": "b", "account_id": "gst", "debit": 18, "credit": ""}],
                "sales_24-25": [
                    {"period": "2024-04", "gstr3b_outward_taxable_value": "100", "books_sales_total": "100", "sales_variance_books_minus_gstr3b": "0"},
                    {"books_sales_total": "100"}],
            }}


def table(report, name):
    return next(s["rows"] for s in report["sheets"] if s["name"] == name)


def test_invoice_match_cannot_hide_credit_net_difference(master, snapshot):
    snapshot["data"]["vendor_credits"] = [{"vendor_credit_id": "c", "vendor_credit_number": "C1", "date": "2024-04-15",
        "status": "open", "vendor_id": "vendor", "vendor_name": "Vendor", "location_id": "root", "location_name": "Root",
        "item_total_without_tax": 20, "total": 23.6}]
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    row = table(report, "Purchase monthly")[0]
    assert row[12] == "Amount difference - review basis"
    assert row[8] == 80 and row[15] == 100
    assert table(report, "Differences")[0][6] == -20


@pytest.mark.parametrize("amount, expected", [(0, "Matches GST net basis"), (100, "No Books purchase in month")])
def test_zero_is_not_missing(master, snapshot, amount, expected):
    master["24-25 GST purchases"][1]["cells"]["G"] = amount
    snapshot["data"]["bills"] = []
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    assert table(report, "Purchase monthly")[0][12] == expected
    assert report["statistics"]["missing"] == int(amount > 0)


def test_supplier_credit_note_bill_is_separate(master, snapshot):
    master["24-25 GST purchases"][1]["cells"]["G"] = 0
    snapshot["data"]["bills"][0]["entity_type"] = "credit_note_vendor"
    snapshot["data"]["input_tax_ledger"][0]["transaction_type"] = "credit_note_vendor"
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    assert table(report, "Purchase monthly")[0][17] == 100
    assert table(report, "Purchase monthly")[0][12] == "Matches GST net basis"


def test_missing_identity_is_unresolved(master, snapshot):
    master["24-25 GST purchases"][1]["cells"]["B"] = "Unknown vendor"
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    assert report["statistics"]["unresolved"] == 1
    assert report["statistics"]["missing"] == 0


def test_inactive_and_other_location_excluded(master, snapshot):
    extra = copy.deepcopy(master["24-25 GST purchases"][1])
    extra["row"] = 3
    extra["cells"]["H"] = "Inactive"
    master["24-25 GST purchases"].append(extra)
    snapshot["data"]["bills"][0]["location_id"] = "other"
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    assert report["statistics"]["source_excluded"] == 1
    assert report["statistics"]["missing"] == 1


def test_tax_credit_counts_debits_not_settlements(master, snapshot):
    snapshot["data"]["accounts"].append({"account_id": "tds", "account_name": "TDS Receivable", "account_type": "other_current_asset"})
    master["24-25 TDS TCS"].append({"row": 2, "cells": {"A": "Business receipts", "B": "TDS-194C", "C": "Vendor", "D": 1,
        "G": "15/04/2024", "H": 500, "I": 10, "J": 0, "K": 10, "L": "Active"}})
    snapshot["data"]["tax_income_ledger"] = [{"account_id": "tds", "date": "2024-04-15", "debit": 10, "credit": 10,
        "contact_id": "vendor", "transaction_type": "journal", "transaction_id": "j", "branch": {"location_name": "Root"}}]
    assert table(reconcile_ais(master, snapshot, gstin=GSTIN), "Tax credits")[0][6] == 10


@pytest.mark.parametrize("field,value", [("G", "NaN"), ("G", ""), ("F", "APR-2025"), ("H", "Deleted")])
def test_invalid_master_fails(master, field, value):
    master["24-25 GST purchases"][1]["cells"][field] = value
    with pytest.raises(ValueError):
        validate_master(master)


def test_snapshot_org_and_completeness_validation(snapshot, tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    assert read_snapshot(path, organization_id="org", from_date="2024-04-01", to_date="2025-03-31")["metadata"]["complete"]
    with pytest.raises(ValueError):
        read_snapshot(path, organization_id="wrong", from_date="2024-04-01", to_date="2025-03-31")
    snapshot["metadata"]["complete"] = False
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError):
        read_snapshot(path, organization_id="org", from_date="2024-04-01", to_date="2025-03-31")


def test_csv_formula_injection_escaped(master, snapshot, tmp_path):
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    report["sheets"][0]["rows"].append(["=HYPERLINK(1)"])
    write_report(report, tmp_path)
    assert "'=HYPERLINK" in (tmp_path / "missing_in_books.csv").read_text(encoding="utf-8-sig")


def test_collection_stops_at_budget_without_mutations(master):
    books = SimpleNamespace(organization_id="org", organizations=SimpleNamespace(get=Mock(return_value={"code": 0})),
                            locations=SimpleNamespace(list=Mock()))
    with pytest.raises(RuntimeError, match="budget"):
        collect_books_snapshot(books, master, CollectionConfig("org", GSTIN, "sales", "other", max_requests=1))
    books.locations.list.assert_not_called()


def test_collection_rejects_missing_list(master):
    books = SimpleNamespace(organization_id="org", organizations=SimpleNamespace(get=Mock(return_value={"code": 0})),
                            locations=SimpleNamespace(list=Mock(return_value={"code": 0, "page_context": {"has_more_page": False}})))
    with pytest.raises(ValueError, match="missing list"):
        collect_books_snapshot(books, master, CollectionConfig("org", GSTIN, "sales", "other", request_interval=1))


def test_collection_normal_path_is_scoped_and_paged(master, snapshot, monkeypatch):
    import workflows.ais_reconciliation.sources as sources
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sources, "compare_gstr3b_to_pnl", lambda *a: snapshot["data"]["sales_24-25"])
    locations = snapshot["data"]["locations"] + [{"location_id": "other", "tax_reg_no": "33ZZZZZ1234F1Z5"}]
    accounts = snapshot["data"]["accounts"] + [{"account_id": "tds", "account_name": "TDS Receivable", "account_type": "other_current_asset"},
        {"account_id": "tcs", "account_name": "TCS Receivable", "account_type": "other_current_asset"},
        {"account_id": "noise", "account_name": "Other Charges", "account_type": "income"}]
    def resource(key, rows):
        return SimpleNamespace(list=Mock(return_value={"code": 0, key: rows, "page_context": {"has_more_page": False}}))
    register = Mock(side_effect=lambda ids, **kw: {"code": 0, "register_transactions": {"account_transactions": []},
        "page_context": {"from_date": kw["from_date"], "to_date": kw["to_date"], "has_more_page": False}})
    books = SimpleNamespace(organization_id="org", organizations=SimpleNamespace(get=Mock(return_value=snapshot["data"]["organization"])),
        locations=resource("locations", locations), chart_of_accounts=resource("chartofaccounts", accounts),
        contacts=resource("contacts", snapshot["data"]["contacts"]), bills=resource("bills", snapshot["data"]["bills"]),
        vendor_credits=resource("vendor_credits", []), expenses=resource("expenses", []),
        registers=SimpleNamespace(list_transactions_for_accounts=register))
    result = collect_books_snapshot(books, master, CollectionConfig("org", GSTIN, "sales", "other"))
    assert result["metadata"]["complete"] is True
    assert result["metadata"]["requests"] == 9
    assert all("noise" not in call.args[0] for call in register.call_args_list)
    assert books.bills.list.call_args.args[0]["per_page"] == 200


def test_collection_repeated_page_is_error(master, snapshot, monkeypatch):
    import workflows.ais_reconciliation.sources as sources
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    page = {"code": 0, "locations": snapshot["data"]["locations"], "page_context": {"has_more_page": True}}
    books = SimpleNamespace(organization_id="org", organizations=SimpleNamespace(get=Mock(return_value={"code": 0})),
                            locations=SimpleNamespace(list=Mock(return_value=page)))
    with pytest.raises(ValueError, match="repeated"):
        collect_books_snapshot(books, master, CollectionConfig("org", GSTIN, "sales", "other"))


def test_replay_uses_new_master_sales_values(master, snapshot):
    master["24-25 GST sales"][1]["cells"]["H"] = 80
    report = reconcile_ais(master, snapshot, gstin=GSTIN)
    assert table(report, "GST sales")[0][2:5] == [80, 100, 20]
    assert any(r[0] == "GST sales" for r in table(report, "Differences"))


def test_bank_ambiguity_is_not_summed_into_a_match(master, snapshot):
    master["Refunds"].append({"row": 2, "cells": {"A": "2024-25", "C": "2023-24", "F": 500, "G": "15/04/2024"}})
    snapshot["data"]["accounts"].append({"account_id": "bank", "account_name": "Bank", "account_type": "bank"})
    snapshot["data"]["bank_windows"] = [{"account_id": "bank", "transaction_id": str(i), "date": "2024-04-15",
        "debit": 500, "credit": 0, "branch": {"location_name": "Root"}} for i in range(2)]
    result = table(reconcile_ais(master, snapshot, gstin=GSTIN), "Tax payments refunds")[0]
    assert result[8] == "Ambiguous candidates"
    assert result[6] is None and result[7] is None


def test_xlsx_reader_and_formula_rejection(master, tmp_path):
    import zipfile
    from xml.etree.ElementTree import Element, SubElement, tostring
    from workflows.ais_reconciliation import read_ais_master
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    book = Element("workbook", xmlns=ns)
    sheets = SubElement(book, "sheets")
    rels = Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    payloads = {}
    for i, (name, rows) in enumerate(master.items(), 1):
        SubElement(sheets, "sheet", name=name, sheetId=str(i), **{"{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": f"r{i}"})
        SubElement(rels, "Relationship", Id=f"r{i}", Target=f"worksheets/s{i}.xml")
        sheet = Element("worksheet", xmlns=ns)
        data = SubElement(sheet, "sheetData")
        for row in rows:
            node = SubElement(data, "row", r=str(row["row"]))
            for col, value in row["cells"].items():
                cell = SubElement(node, "c", r=f"{col}{row['row']}", t="inlineStr")
                SubElement(SubElement(cell, "is"), "t").text = str(value)
        payloads[f"xl/worksheets/s{i}.xml"] = tostring(sheet)
    def save(path, formulas=False):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", tostring(book))
            archive.writestr("xl/_rels/workbook.xml.rels", tostring(rels))
            for name, payload in payloads.items():
                if formulas and name.endswith("s1.xml"):
                    payload = payload.replace(b"<is>", b"<f>1+1</f><is>", 1)
                archive.writestr(name, payload)
    path = tmp_path / "master.xlsx"
    save(path)
    assert read_ais_master(path)["24-25 GST purchases"][1]["cells"]["G"] == "100"
    save(path, True)
    with pytest.raises(ValueError, match="Formula"):
        read_ais_master(path)
