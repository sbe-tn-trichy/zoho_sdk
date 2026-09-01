"""Parse Polycab RSO PDFs and import them as Zoho Books sales orders."""

from __future__ import annotations

import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pdfplumber

from zoho.helpers import find_transaction_by_number, unwrap_record
from ..core.config import Config


_ITEM_ROW = re.compile(
    r"^\s*(?P<sequence>\d+)\s+"
    r"(?P<sku>[A-Z0-9]+)\s+.*?\bNUMBERS\s+"
    r"(?P<quantity>\d+(?:\.\d+)?)\s+T\.B\.PD\s+"
    r"[\d,.]+\s+[\d,.]+\s+"
    r"(?P<rate>[\d,.]+)\s+Yes\s+"
    r"(?P<amount>[\d,.]+)\s*$",
    re.MULTILINE,
)

_SKU_OVERRIDES = {
    "FCEECST303M": "FCEECS-T187M",
    "FTANSST033P": "FTANSS-T024P",
    "LDO0119012": "LP0302-012RDCW",
}


def _required_match(pattern: str, text: str, field: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find {field} in the RSO PDF.")
    return match.group(1).strip()


def _parse_pdf_date(raw_date: str, field: str) -> str:
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw_date.upper(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Invalid {field}: {raw_date!r}")


def parse_polycab_rso_pdf(pdf_path: str) -> Dict[str, Any]:
    """Extract one Polycab RSO, stopping the item scan at the first Total row."""
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(
            (page.extract_text(layout=True) or "") for page in pdf.pages
        )
    if not text.strip():
        raise ValueError(f"No extractable text found in PDF: {pdf_path}")

    sales_order_number = _required_match(
        r"Sales Order Number\s*:\s*(\d+)", text, "Sales Order Number"
    )
    entered_date_raw = _required_match(
        r"SO Entered Date\s*:\s*([\w-]+)", text, "SO Entered Date"
    )
    booked_date_raw = _required_match(
        r"SO Booked Date\s*:\s*([\w-]+)", text, "SO Booked Date"
    )
    order_type = _required_match(
        r"Order Type\s*:\s*([^\r\n]+)", text, "Order Type"
    ).split()[0]

    customer_line = _required_match(
        r"Customer Name\s*:\s*(.+?)\s+Sales Order Number\s*:",
        text,
        "Customer Name",
    )
    customer_match = re.match(r"(.+?)\s+-\s+(\d+)$", customer_line)
    customer_name = customer_match.group(1).strip() if customer_match else customer_line
    customer_code = customer_match.group(2) if customer_match else None

    item_heading = re.search(r"(?im)^\s*ITEM DETAILS\s*$", text)
    if not item_heading:
        raise ValueError("Could not find ITEM DETAILS in the RSO PDF.")
    item_section = text[item_heading.end():]
    total_match = re.search(
        r"(?im)^\s*Total Rs\.\s+([\d,.]+)\s*$", item_section
    )
    if not total_match:
        raise ValueError("Could not find the first Total Rs. row in the RSO PDF.")

    # The PDF repeats every item under LINE DETAILS. Confining extraction to this
    # prefix is the workflow's hard stop and prevents duplicate line creation.
    primary_item_table = item_section[:total_match.start()]
    items: List[Dict[str, Any]] = []
    for match in _ITEM_ROW.finditer(primary_item_table):
        quantity = Decimal(match.group("quantity"))
        rate = Decimal(match.group("rate").replace(",", ""))
        amount = Decimal(match.group("amount").replace(",", ""))
        items.append(
            {
                "sequence": int(match.group("sequence")),
                "sku": match.group("sku"),
                "quantity": float(quantity),
                "rate": float(rate),
                "amount": float(amount),
            }
        )

    if not items:
        raise ValueError("No item rows were found before the first Total Rs. row.")
    expected_sequences = list(range(1, len(items) + 1))
    actual_sequences = [item["sequence"] for item in items]
    if actual_sequences != expected_sequences:
        raise ValueError(
            "RSO item sequence is incomplete before Total Rs.: "
            f"expected {expected_sequences}, found {actual_sequences}."
        )

    subtotal = Decimal(total_match.group(1).replace(",", ""))
    parsed_subtotal = sum(Decimal(str(item["amount"])) for item in items)
    if abs(parsed_subtotal - subtotal) > Decimal("0.02"):
        raise ValueError(
            f"RSO item total {parsed_subtotal} does not match Total Rs. {subtotal}."
        )

    grand_total_match = re.search(r"Grand Total\s+([\d,.]+)", item_section)
    grand_total = (
        float(Decimal(grand_total_match.group(1).replace(",", "")))
        if grand_total_match
        else None
    )

    return {
        "sales_order_number": sales_order_number,
        "customer_name": customer_name,
        "customer_code": customer_code,
        "date": _parse_pdf_date(entered_date_raw, "SO Entered Date"),
        "booked_date": _parse_pdf_date(booked_date_raw, "SO Booked Date"),
        "order_type": order_type,
        "subtotal": float(subtotal),
        "grand_total": grand_total,
        "items": items,
    }


def _find_existing_sales_order(books_client: Any, rso_number: str) -> Optional[Dict[str, Any]]:
    return find_transaction_by_number(
        books_client.sales_orders,
        rso_number,
        number_keys=("reference_number", "salesorder_number"),
        resource_key="salesorders",
    )


def _resolve_line_items(books_client: Any, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    resolved_by_sku: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for sku in dict.fromkeys(item["sku"] for item in items):
        # Polycab prints compact codes such as FPENSST008P while the Books
        # catalog uses its canonical six-character-prefix form FPENSS-T008P.
        candidate_skus = [_SKU_OVERRIDES[sku]] if sku in _SKU_OVERRIDES else [sku]
        if sku not in _SKU_OVERRIDES and len(sku) > 6 and "-" not in sku:
            candidate_skus.append(f"{sku[:6]}-{sku[6:]}")

        matches: List[Dict[str, Any]] = []
        for candidate in candidate_skus:
            response = books_client.items.list(params={"sku": candidate})
            matches = [
                item
                for item in response.get("items", [])
                if str(item.get("sku") or "").upper() == candidate.upper()
            ]
            if matches:
                matches.sort(key=lambda item: item.get("status") != "active")
                break
        if not matches or not matches[0].get("item_id"):
            missing.append(sku)
        else:
            resolved_by_sku[sku] = matches[0]
    if missing:
        raise ValueError(
            "These RSO SKUs do not exist in Zoho Books: " + ", ".join(missing)
        )

    return [
        {
            "item_id": resolved_by_sku[item["sku"]]["item_id"],
            "quantity": item["quantity"],
            "rate": item["rate"],
        }
        for item in items
    ]


def import_polycab_rso_pdf(
    books_client: Any,
    pdf_path: str,
    customer_id: str = Config.RSO_CUSTOMER_ID,
    location_id: str = Config.EXPECTED_LOCATION_ID,
) -> Dict[str, Any]:
    """Create an idempotent Books sales order from an RSO PDF and attach it."""
    details = parse_polycab_rso_pdf(pdf_path)
    rso_number = details["sales_order_number"]
    existing = _find_existing_sales_order(books_client, rso_number)
    if existing:
        attachment_uploaded = False
        if not existing.get("has_attachment"):
            sales_order_id = existing.get("salesorder_id")
            if not sales_order_id:
                raise ValueError(f"Existing sales order {rso_number} has no ID.")
            books_client.sales_orders.add_attachment(sales_order_id, pdf_path)
            attachment_uploaded = True
        return {
            "created": False,
            "attachment_uploaded": attachment_uploaded,
            "sales_order": existing,
            "parsed": details,
        }

    line_items = _resolve_line_items(books_client, details["items"])
    payload = {
        "customer_id": customer_id,
        "location_id": location_id,
        "salesorder_number": rso_number,
        "reference_number": rso_number,
        "date": details["date"],
        "line_items": line_items,
        "notes": (
            f"Imported from Polycab RSO {rso_number}; "
            f"order type {details['order_type']}; booked {details['booked_date']}"
        ),
    }
    try:
        response = books_client.sales_orders.create(payload)
    except Exception as exc:
        if "4097" not in str(exc) and "auto-generated number" not in str(exc):
            raise
        payload.pop("salesorder_number", None)
        response = books_client.sales_orders.create(payload)

    sales_order = unwrap_record(response, ("salesorder", "sales_order"))
    sales_order_id = sales_order.get("salesorder_id")
    if not sales_order_id:
        raise ValueError(f"Created sales order {rso_number} response has no ID.")
    books_client.sales_orders.add_attachment(sales_order_id, pdf_path)
    return {
        "created": True,
        "attachment_uploaded": True,
        "sales_order": sales_order,
        "parsed": details,
    }
