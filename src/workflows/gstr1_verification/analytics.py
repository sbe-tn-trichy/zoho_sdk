"""Read Analytics Books tables into the verifier's document format."""

from datetime import date
from typing import Any

from zoho.helpers import parse_date


def load_records(client: Any, workspace_id: str, source: str,
                 errors: list[dict[str, str]], start: date | None = None,
                 end: date | None = None) -> list[dict[str, Any]]:
    tables = {"locations": "Locations", "invoices": "Invoices", "credit_notes": "Credit Notes"}
    sql = f'SELECT * FROM "{tables[source]} (Zoho Books)"'
    prefix = "Invoice" if source == "invoices" else "Credit Note"
    if start is not None and end is not None:
        sql += (f' WHERE "{prefix} Date" >= \'{start.isoformat()}\''
                f' AND "{prefix} Date" <= \'{end.isoformat()}\'')
    try:
        rows = client.queries.execute(workspace_id, sql, max_attempts=60)
        return [_normalize(row, source) for row in rows]
    except Exception as exc:
        errors.append({"source": f"analytics_{source}", "error": str(exc)})
        return []


def _normalize(row: dict[str, Any], source: str) -> dict[str, Any]:
    def value(*names: str) -> Any:
        return next((row[name] for name in names if row.get(name) not in (None, "")), None)

    result = {
        "location_id": value("Location ID", "location_id"),
        "location_name": value("Location Name", "location_name"),
    }
    if source == "locations":
        if not result["location_id"]:
            raise ValueError("Analytics location is missing Location ID.")
        result.update(tax_reg_no=value("GSTIN", "GST Identification Number (GSTIN)",
                                      "GST Number", "Tax Registration Number", "tax_reg_no"),
                      tax_settings_id=value("Tax Settings ID", "tax_settings_id"))
        return result

    prefix, key = ("Invoice", "invoice") if source == "invoices" else ("Credit Note", "creditnote")
    document_date = parse_date(value(f"{prefix} Date", "date"))
    result.update({
        f"{key}_id": value(f"{prefix} ID", "CreditNotes ID" if key == "creditnote" else "Invoice ID",
                           f"{key}_id"),
        f"{key}_number": value(f"{prefix} Number", f"{key}_number"),
        "date": document_date.isoformat() if document_date else None,
        "status": str(value(f"{prefix} Status", "Status", "status") or "").lower(),
        "customer_name": value("Customer Name", "customer_name"),
        "customer_id": value("Customer ID", "customer_id"),
        "total": value("Total (BCY)", "Total", "total"),
    })
    if not all(result[field] for field in (f"{key}_id", f"{key}_number", "date", "status")):
        raise ValueError(f"Analytics {prefix} is missing an ID, number, valid date, or status.")
    details = value("einvoice_details")
    if isinstance(details, dict):
        result["einvoice_details"] = details
    else:
        status = value("e-Invoice Status.", "E-Invoice Status", "e-Invoice Status",
                       "E Invoice Status", "einvoice_status")
        # Missing exported evidence must not silently pass the e-invoice check.
        if str(status or "").casefold() not in {"not applicable", "not_applicable"}:
            result["einvoice_details"] = {
                "einvoice_status": status or "unknown",
                "inv_ref_num": value("e-Invoice Reference Number.", "IRN",
                                     "Invoice Reference Number", "inv_ref_num"),
            }
    return result
