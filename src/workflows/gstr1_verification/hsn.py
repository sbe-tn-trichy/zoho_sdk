"""Analytics evidence for customer credit-note HSN validation."""

import calendar
import re
from datetime import date
from typing import Any, Mapping, Sequence, TypedDict

from zoho.helpers import parse_date


class HSNLine(TypedDict):
    document_id: str
    document_number: str
    customer_id: str
    customer_name: str
    date: date
    status: str
    location_id: str
    line_id: str
    hsn: str
    gst_treatment: str
    customer_gst_treatment: str


class HSNCheck(TypedDict):
    source: str
    skipped: bool
    complete: bool
    passed: bool
    checked_lines: int
    matched: list[dict[str, Any]]
    financial_credit_notes: list[dict[str, Any]]
    violations: list[dict[str, Any]]
    unverifiable: list[dict[str, Any]]


def _hsn(value: Any) -> str:
    text = str(value or "").strip()
    # Analytics may serialize integer codes as floating-point values.
    return re.sub(r"\.0+$", "", text)


def _six_months_before(value: date) -> date:
    month_index = value.year * 12 + value.month - 1 - 6
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _sales_type(line: HSNLine) -> str | None:
    treatment = line["gst_treatment"] or line["customer_gst_treatment"]
    token = re.sub(r"[^a-z0-9]", "", treatment.casefold())
    if token in {"b2c", "consumer", "unregisteredbusiness", "businessnone"}:
        return "B2C"
    if token in {"b2b", "registeredbusinessregular", "registeredbusinesscomposition",
                 "businessgst", "businessregistered", "businesscomposition"}:
        return "B2B"
    return None


def _normalize(row: Mapping[str, Any]) -> HSNLine:
    parsed = parse_date(row.get("date"))
    if parsed is None or not row.get("document_id") or not row.get("status"):
        raise ValueError("HSN export is missing a document ID, status, or valid date.")
    return HSNLine(document_id=str(row["document_id"]),
                   document_number=str(row.get("document_number") or ""),
                   customer_id=str(row.get("customer_id") or ""),
                   customer_name=str(row.get("customer_name") or ""),
                   date=parsed, status=str(row["status"]).strip().casefold(),
                   location_id=str(row.get("location_id") or ""),
                   line_id=str(row.get("line_id") or ""), hsn=_hsn(row.get("hsn")),
                   gst_treatment=str(row.get("gst_treatment") or "").strip(),
                   customer_gst_treatment=str(row.get("customer_gst_treatment") or "").strip())


def load_hsn_evidence(client: Any, workspace_id: str, start: date, end: date,
                      errors: list[dict[str, str]]) -> tuple[list[HSNLine], list[HSNLine], bool]:
    """Read monthly credits, customer invoice history and pooled six-month sales."""
    if client is None:
        errors.append({"source": "analytics_credit_note_hsn", "error": "An Analytics client is required for credit-note HSN validation."})
        return [], [], False
    credits: list[HSNLine] = []
    invoices: list[HSNLine] = []
    complete = True
    customer_scope = (f'SELECT "Customer ID" FROM "Credit Notes (Zoho Books)" '
                      f'WHERE "Credit Note Date" >= \'{start.isoformat()}\' '
                      f'AND "Credit Note Date" <= \'{end.isoformat()}\'')
    for source, table, line_table, id_column, prefix in (
        ("credit_note_hsn", "Credit Notes", "Credit Note Items", "CreditNotes ID", "Credit Note"),
        ("invoice_hsn", "Invoices", "Invoice Items", "Invoice ID", "Invoice"),
    ):
        sql = (f'SELECT D."{id_column}" AS "document_id", D."{prefix} Number" AS "document_number", '
               f'D."Customer ID" AS "customer_id", C."Customer Name" AS "customer_name", '
               f'D."GST Treatment" AS "gst_treatment", C."GST Treatment" AS "customer_gst_treatment", '
               f'D."{prefix} Date" AS "date", D."{prefix} Status" AS "status", '
               f'D."Location ID" AS "location_id", L."Item ID" AS "line_id", L."HSN/SAC" AS "hsn" '
               f'FROM "{table} (Zoho Books)" D '
               f'LEFT JOIN "{line_table} (Zoho Books)" L ON D."{id_column}" = L."{id_column}" '
               f'LEFT JOIN "Customers (Zoho Books)" C ON D."Customer ID" = C."Customer ID" '
               f'WHERE D."{prefix} Date" <= \'{end.isoformat()}\' ')
        if source == "credit_note_hsn":
            sql += f'AND D."Credit Note Date" >= \'{start.isoformat()}\''
        else:
            sql += (f'AND (D."Customer ID" IN ({customer_scope}) '
                    f'OR D."Invoice Date" >= \'{_six_months_before(start).isoformat()}\')')
        try:
            rows = [_normalize(row) for row in client.queries.execute(workspace_id, sql, max_attempts=60)]
            if source == "credit_note_hsn":
                credits = rows
            else:
                invoices = rows
        except Exception as exc:
            complete = False
            errors.append({"source": f"analytics_{source}", "error": str(exc)})
    return credits, invoices, complete


def check_credit_note_hsn(documents: Sequence[Mapping[str, Any]],
                          credits: Sequence[HSNLine], invoices: Sequence[HSNLine],
                          location_to_registration: Mapping[str, str], *,
                          evidence_complete: bool, enabled: bool = True,
                          financial_credit_note_ids: Sequence[str] = ()) -> HSNCheck:
    """Validate B2B customer history and B2C six-month pooled sales by GSTIN."""
    result: HSNCheck = {"source": "analytics", "skipped": not enabled,
                              "complete": True, "passed": True, "checked_lines": 0,
                              "matched": [], "financial_credit_notes": [], "violations": [], "unverifiable": []}
    if not enabled:
        return result
    active = [doc for doc in documents if str(doc.get("status") or "").strip().casefold() not in {"draft", "void"}]
    financial_ids = set(financial_credit_note_ids)
    for doc in active:
        doc_id = str(doc.get("creditnote_id") or doc.get("credit_note_id") or "")
        if doc_id in financial_ids:
            result["financial_credit_notes"].append({"credit_note_id": doc_id,
                "credit_note_number": doc.get("creditnote_number") or doc.get("credit_note_number"),
                "date": doc.get("date"), "customer_name": doc.get("customer_name"),
                "reason": "Confirmed financial credit note; GST not applicable. HSN validation excluded."})
    active = [doc for doc in active
              if str(doc.get("creditnote_id") or doc.get("credit_note_id") or "") not in financial_ids]
    if not active:
        return result
    if not evidence_complete:
        result.update(complete=False, passed=False)
        return result
    credit_lines: dict[str, list[HSNLine]] = {}
    invoice_lines: dict[tuple[str, str], list[HSNLine]] = {}
    registration_invoices: dict[str, list[HSNLine]] = {}
    unscoped_invoices: list[HSNLine] = []
    for line in credits:
        credit_lines.setdefault(line["document_id"], []).append(line)
    for line in invoices:
        if line["status"] not in {"draft", "void"}:
            registration = location_to_registration.get(line["location_id"])
            if registration:
                invoice_lines.setdefault((registration, line["customer_id"]), []).append(line)
                registration_invoices.setdefault(registration, []).append(line)
            else:
                unscoped_invoices.append(line)
    for doc in active:
        doc_id = str(doc.get("creditnote_id") or doc.get("credit_note_id") or "")
        lines = credit_lines.get(doc_id, [])
        base = {"credit_note_id": doc_id, "credit_note_number": doc.get("creditnote_number") or doc.get("credit_note_number"),
                "date": doc.get("date"), "location_id": doc.get("location_id")}
        if not lines:
            result["unverifiable"].append({**base, "reason": "Credit note absent from Analytics evidence; synchronization may be pending."})
        for line in lines:
            detail = {**base, "customer_id": line["customer_id"], "customer_name": line["customer_name"],
                      "line_id": line["line_id"], "hsn": line["hsn"],
                      "gst_treatment": line["gst_treatment"], "customer_gst_treatment": line["customer_gst_treatment"]}
            registration = location_to_registration.get(line["location_id"])
            if (not registration or not line["customer_id"] or not line["line_id"] or not line["hsn"]
                    or line["status"] in {"draft", "void"}
                    or line["date"] != parse_date(doc.get("date"))
                    or str(doc.get("location_id") or "") != line["location_id"]
                    or (doc.get("customer_id") and str(doc["customer_id"]) != line["customer_id"])):
                result["unverifiable"].append({**detail, "reason": "Missing identity, GST registration, line HSN, or conflicting synced credit-note metadata."})
                continue
            sales_type = _sales_type(line)
            if sales_type is None:
                result["unverifiable"].append({**detail, "reason": "GST treatment is missing or unsupported; cannot select B2B/B2C HSN rule."})
                continue
            detail["sales_type"] = sales_type
            lower = _six_months_before(line["date"]) if sales_type == "B2C" else date.min
            detail["rule"] = "B2C: any customer, preceding six months" if sales_type == "B2C" else "B2B: same customer, all prior history"
            candidates = (registration_invoices.get(registration, []) if sales_type == "B2C"
                          else invoice_lines.get((registration, line["customer_id"]), []))
            history = [item for item in candidates if lower <= item["date"] <= line["date"]]
            result["checked_lines"] += 1
            matches = [item for item in history if item["hsn"] == line["hsn"] and item["line_id"]]
            if matches:
                match = min(matches, key=lambda item: (item["date"], item["document_id"], item["line_id"]))
                result["matched"].append({**detail, "matching_invoice_number": match["document_number"],
                                          "matching_invoice_date": match["date"].isoformat(),
                                          "matching_customer_id": match["customer_id"],
                                          "matching_customer_name": match["customer_name"]})
                continue
            if (any(not item["hsn"] or not item["line_id"] for item in history)
                    or any((sales_type == "B2C" or item["customer_id"] == line["customer_id"])
                           and lower <= item["date"] <= line["date"]
                           for item in unscoped_invoices)):
                result["unverifiable"].append({**detail, "reason": "Prior invoice lines have missing HSN evidence."})
                continue
            result["violations"].append({**detail,
                "invoice_hsns": sorted({item["hsn"] for item in history}),
                "reason": ("Credit-note HSN absent from invoices under the same seller GSTIN in the preceding six months."
                           if sales_type == "B2C" else "Credit-note HSN absent from prior invoices for the same customer and seller GSTIN.")})
    result["complete"] = not result["unverifiable"]
    result["passed"] = result["complete"] and not result["violations"]
    return result
