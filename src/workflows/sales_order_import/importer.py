"""Invoice parsing and explicit item-creation policy outside the SDK."""

from dataclasses import dataclass
from datetime import datetime
import math
from decimal import Decimal
from typing import Any, Mapping

from zoho.exceptions import ZohoError
from zoho.helpers.items import find_item_by_exact_sku
from workflows.core.matching import to_finite_decimal


@dataclass(frozen=True)
class InvoiceLine:
    sku: str
    name: str
    quantity: Decimal
    rate: Decimal


@dataclass(frozen=True)
class InvoiceData:
    number: str
    date: str
    lines: tuple[InvoiceLine, ...]


@dataclass(frozen=True)
class ItemCreationPolicy:
    """Legacy fan/heater policy; callers can supply explicit business defaults."""
    heater_hsn: str = "8516"
    other_hsn: str = "8414"
    purchase_rate_divisor: Decimal = Decimal("1.12")
    tax_name: str = "GST18"
    tax_percentage: Decimal = Decimal("18")
    unit: str = "NOS"


class SalesOrderImportError(RuntimeError):
    """Failed import exposing created item IDs for manual recovery."""
    def __init__(self, message: str, created_item_ids: tuple[str, ...]):
        super().__init__(message)
        self.created_item_ids = created_item_ids


def parse_invoice_yaml(yaml_str: str) -> InvoiceData:
    """Parse the established flat/indented scalar dialect, rejecting malformed rows.

    This deliberately is not a general YAML loader: nested values, anchors and
    multiline scalars are unsupported. Both `no` and legacy `False` keys work.
    """
    sections: dict[str, Any] = {"inv": {}, "items": [], "totals": {}}
    section = None
    item = None
    seen_sections = set()
    for line_no, raw in enumerate(yaml_str.splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        starts_item = text.startswith("- ")
        if starts_item:
            text = text[2:].strip()
        if text in {"inv:", "items:", "totals:"}:
            section = text[:-1]
            if section in seen_sections:
                raise ValueError(f"Repeated section on line {line_no}")
            seen_sections.add(section)
            continue
        if section is None or ":" not in text:
            raise ValueError(f"Invalid invoice line {line_no}")
        key, value = (part.strip() for part in text.split(":", 1))
        if value[:1] in {"\"", "'"}:
            if len(value) < 2 or value[0] != value[-1]:
                raise ValueError(f"Unclosed scalar quote on line {line_no}")
            value = value[1:-1]
        elif value[:1] in {"[", "{", "&", "*", "!", "|", ">"}:
            raise ValueError(f"Unsupported YAML value on line {line_no}")
        if section == "items":
            if starts_item or key == "sku":
                item = {}
                sections["items"].append(item)
            if item is None or key in item:
                raise ValueError(f"Invalid or duplicate item field on line {line_no}")
            item[key] = value
        else:
            key = "no" if section == "inv" and key == "False" else key
            if key in sections[section]:
                raise ValueError(f"Duplicate invoice field on line {line_no}")
            sections[section][key] = value
    invoice = sections["inv"]
    if not invoice.get("no") or not invoice.get("date") or not sections["items"]:
        raise ValueError("Invalid YAML structure: invoice no, date and items are required")
    normalized_date = None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            normalized_date = datetime.strptime(invoice["date"], fmt).date().isoformat()
            break
        except ValueError:
            continue
    if normalized_date is None:
        raise ValueError(f"Could not parse date: {invoice['date']}")
    lines = []
    for index, row in enumerate(sections["items"], 1):
        quantity = to_finite_decimal(row.get("qty"))
        rate = to_finite_decimal(row.get("rate"))
        if (not row.get("sku") or not row.get("name") or quantity is None
                or quantity <= 0 or rate is None or rate < 0
                or not math.isfinite(float(quantity)) or not math.isfinite(float(rate))):
            raise ValueError(f"Invalid invoice item {index}: sku, name, positive qty and nonnegative rate required")
        lines.append(InvoiceLine(row["sku"], row["name"], quantity, rate))
    return InvoiceData(invoice["no"], normalized_date, tuple(lines))


def create_sales_order_from_yaml(
    books_client: Any, yaml_str: str, customer_id: str,
    create_missing_items: bool = False, default_accounts: Mapping[str, str] | None = None,
    *, inventory_client: Any, purchase_account_id: str | None = None,
    item_policy: ItemCreationPolicy = ItemCreationPolicy(),
) -> dict[str, Any]:
    """Validate all rows, resolve exact SKUs, then create items/order if requested."""
    if not customer_id:
        raise ValueError("customer_id is required to create a sales order.")
    invoice = parse_invoice_yaml(yaml_str)
    scope = purchase_account_id or (default_accounts or {}).get("purchase_account_id")
    if purchase_account_id is not None and not purchase_account_id.strip():
        raise ValueError("purchase_account_id cannot be empty")
    if create_missing_items:
        if not default_accounts or not all(default_accounts.get(k) for k in
                ("account_id", "purchase_account_id", "inventory_account_id")):
            raise ValueError("default_accounts with sales, purchase and inventory accounts are required")
        if scope != default_accounts["purchase_account_id"]:
            raise ValueError("Catalog scope and item purchase account must match")
        divisor = to_finite_decimal(item_policy.purchase_rate_divisor)
        tax = to_finite_decimal(item_policy.tax_percentage)
        if (divisor is None or divisor <= 0 or tax is None or not 0 <= tax <= 100
                or not all((item_policy.heater_hsn, item_policy.other_hsn, item_policy.tax_name, item_policy.unit))):
            raise ValueError("Invalid item creation policy")
        try:
            purchase_rates = {(line.sku, line.rate): float(round(line.rate / divisor, 2)) for line in invoice.lines}
        except ArithmeticError as exc:
            raise ValueError("Purchase rate exceeds supported numeric range") from exc
        if any(not math.isfinite(rate) for rate in purchase_rates.values()):
            raise ValueError("Purchase rate exceeds supported numeric range")
    catalog = {}
    for line in invoice.lines:
        if line.sku in catalog:
            continue
        if scope:
            match = find_item_by_exact_sku(inventory_client, line.sku, scope)
        else:
            response = inventory_client.items.list(params={"sku": line.sku})
            matches = [item for item in response.get("items", [])
                       if str(item.get("sku") or "").upper() == line.sku.upper()]
            matches.sort(key=lambda item: item.get("status") != "active")
            match = matches[0] if matches else None
        if match is not None and not match.get("item_id"):
            raise ValueError(f"Inventory item lacks item_id: {line.sku}")
        if match is None and not create_missing_items:
            raise ValueError(f"Item with SKU '{line.sku}' not found in Zoho Inventory")
        catalog[line.sku] = match
    created = []
    try:
        for line in invoice.lines:
            if catalog[line.sku] is not None:
                continue
            payload = {
                "name": line.name, "sku": line.sku,
                "hsn_or_sac": item_policy.heater_hsn if "HEATER" in line.name.upper() or "HWH" in line.sku.upper() else item_policy.other_hsn,
                "rate": float(line.rate),
                "purchase_rate": purchase_rates[(line.sku, line.rate)],
                **{key: default_accounts[key] for key in ("account_id", "purchase_account_id", "inventory_account_id")},
                "item_tax_preferences": [{"tax_name": item_policy.tax_name, "tax_percentage": float(tax)}],
                "is_taxable": True, "product_type": "goods", "unit": item_policy.unit,
                "track_inventory": True, "inventory_valuation_method": "fifo",
                "can_be_sold": True, "can_be_purchased": True,
            }
            response = inventory_client.items.create(payload)
            item = response.get("item") or {}
            if response.get("code", 0) != 0 or not item.get("item_id"):
                raise ValueError(f"Inventory did not confirm item creation: {line.sku}")
            created.append(str(item["item_id"]))
            catalog[line.sku] = item
        payload = {
            "customer_id": customer_id, "salesorder_number": f"SO-{invoice.number}",
            "reference_number": invoice.number, "date": invoice.date,
            "line_items": [{"item_id": catalog[line.sku]["item_id"],
                            "name": catalog[line.sku].get("name") or line.name,
                            "quantity": float(line.quantity), "rate": float(line.rate),
                            "description": line.name} for line in invoice.lines],
            "notes": f"Generated automatically from invoice YAML {invoice.number}",
        }
        try:
            response = books_client.sales_orders.create(payload)
        except ZohoError as exc:
            if str(exc.error_code) != "4097":
                raise
            payload.pop("salesorder_number")
            response = books_client.sales_orders.create(payload)
        if response.get("code", 0) != 0:
            raise ValueError(f"Books rejected sales order: {response.get('message')}")
        return response
    except Exception as exc:
        raise SalesOrderImportError(str(exc), tuple(created)) from exc
