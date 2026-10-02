"""Read the AIS IT workbook without an optional Excel dependency."""
from __future__ import annotations

import posixpath
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict
from xml.etree import ElementTree as ET
from workflows.core.matching import to_finite_decimal


class MasterRow(TypedDict):
    row: int
    cells: dict[str, Any]


Master = dict[str, list[MasterRow]]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_ais_master(path: Path | str) -> Master:
    """Parse and validate the supplied AIS IT tabular export; reject cached formulas."""
    result: Master = {}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                       for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in
                ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).find("m:sheets", NS):
            target = rels[sheet.attrib[RID]]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            if not target.startswith("xl/"):
                raise ValueError("Workbook relationship is outside xl/")
            rows = []
            for row in ET.fromstring(archive.read(target)).findall("m:sheetData/m:row", NS):
                cells = {}
                for cell in row:
                    if cell.find("m:f", NS) is not None:
                        raise ValueError(f"Formula in AIS master: {sheet.attrib['name']}!{cell.attrib['r']}")
                    value = cell.find("m:v", NS)
                    kind = cell.attrib.get("t")
                    if kind == "s":
                        parsed = strings[int(value.text)]
                    elif kind == "inlineStr":
                        parsed = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                    elif kind == "e":
                        raise ValueError("Excel error in AIS master")
                    elif value is None:
                        continue
                    elif kind == "str":
                        parsed = value.text
                    else:
                        amount = to_finite_decimal(value.text)
                        if amount is None:
                            raise ValueError("Non-finite AIS number")
                        parsed = str(amount)
                    cells[re.sub(r"\d", "", cell.attrib["r"])] = parsed
                if cells:
                    rows.append({"row": int(row.attrib["r"]), "cells": cells})
            result[sheet.attrib["name"]] = rows
    validate_master(result)
    return result


def validate_master(master: Master) -> None:
    prefixes = [name.removesuffix(" GST purchases") for name in master if name.endswith(" GST purchases")]
    if not prefixes:
        raise ValueError("Missing AIS GST purchases tabs")
    headers = {
        "GST purchases": {"B": "supplier", "E": "GSTIN", "F": "Return period", "G": "Purchase", "H": "Status"},
        "GST sales": {"E": "GSTIN", "F": "Return period", "H": "Taxable", "I": "Status"},
        "TDS TCS": {"B": "Code", "G": "Payment", "H": "Amount", "L": "Status"},
        "Source totals": {"A": "Group", "F": "Reported amount"},
    }
    for prefix in prefixes:
        if not re.fullmatch(r"\d{2}-\d{2}", prefix):
            raise ValueError(f"Unsupported AIS year label: {prefix}")
        year = 2000 + int(prefix[:2])
        if int(prefix[3:]) != (year + 1) % 100:
            raise ValueError("AIS year label is not a consecutive financial year")
        for suffix, expected in headers.items():
            name = prefix + " " + suffix
            if not master.get(name):
                raise ValueError(f"Missing AIS tab: {name}")
            for col, text in expected.items():
                if text.casefold() not in str(master[name][0]["cells"].get(col, "")).casefold():
                    raise ValueError(f"Unsupported AIS layout: {name} column {col}")
            status_col = {"GST purchases": "H", "GST sales": "I", "TDS TCS": "L"}.get(suffix)
            if status_col:
                for row in master[name][1:]:
                    if row["cells"].get(status_col) not in {"Active", "Inactive"}:
                        raise ValueError(f"Unknown AIS status: {name}!{row['row']}")
                    c = row["cells"]
                    monetary = {"GST purchases": ("G",), "GST sales": ("G", "H"), "TDS TCS": ("H",)}[suffix]
                    for col in monetary:
                        if to_finite_decimal(c.get(col), allow_commas=True) is None:
                            raise ValueError(f"Invalid AIS amount: {name}!{col}{row['row']}")
                    col = "G" if suffix == "TDS TCS" else "F"
                    day = datetime.strptime(c[col], "%d/%m/%Y" if suffix == "TDS TCS" else "%b-%Y")
                    if not datetime(year, 4, 1) <= day < datetime(year + 1, 4, 1):
                        raise ValueError(f"AIS date outside tab financial year: {name}!{row['row']}")
    for name in ("Tax payments", "Refunds"):
        if name not in master:
            raise ValueError(f"Missing AIS tab: {name}")
