from typing import Any, Dict, Optional
from ..base import BaseResource
from ..mixins import StatusMixin, EmailMixin, ApprovalMixin, CreditsMixin

class Invoices(BaseResource, StatusMixin, EmailMixin, ApprovalMixin, CreditsMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'invoices')

    def apply_credits(self, invoice_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', invoice_id, 'credits', data=data)

class Estimates(BaseResource, StatusMixin, EmailMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'estimates')

    def mark_as_accepted(self, estimate_id: str) -> Dict[str, Any]:
        return self._action('POST', estimate_id, 'status/accepted')

    def mark_as_declined(self, estimate_id: str) -> Dict[str, Any]:
        return self._action('POST', estimate_id, 'status/declined')

class SalesOrders(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'salesorders')

    def create_from_yaml(self, yaml_str: str, customer_id: str = "1094368000001317103", create_missing_items: bool = False) -> Dict[str, Any]:
        """
        Create a Sales Order in Zoho Books from a flat or standard invoice YAML string.
        Resolves items by SKU (optionally creating them if missing when create_missing_items=True).
        """
        import yaml
        from datetime import datetime
        
        # 1. Custom line-by-line YAML parser to handle flat formats
        data = {
            "inv": {},
            "items": [],
            "totals": {}
        }
        current_section = None
        current_item = None
        
        for line in yaml_str.splitlines():
            line = line.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if not line:
                continue
            if line.startswith("inv:"):
                current_section = "inv"
                continue
            elif line.startswith("items:"):
                current_section = "items"
                continue
            elif line.startswith("totals:"):
                current_section = "totals"
                continue
                
            if ":" in line:
                parts = line.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                    
                if current_section == "inv":
                    if key in ("no", "False"):
                        data["inv"]["no"] = val
                    else:
                        data["inv"][key] = val
                elif current_section == "totals":
                    data["totals"][key] = val
                elif current_section == "items":
                    if key == "sku":
                        if current_item:
                            data["items"].append(current_item)
                        current_item = {"sku": val}
                    elif current_item is not None:
                        current_item[key] = val
                        
        if current_item:
            data["items"].append(current_item)
            
        if not data or 'inv' not in data or not data['inv'] or not data['items']:
            raise ValueError("Invalid YAML structure. Must contain 'inv' and 'items'.")
            
        # 2. Normalize date
        inv_date = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                inv_date = datetime.strptime(data['inv']['date'].strip(), fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if not inv_date:
            raise ValueError(f"Could not parse date: {data['inv']['date']}")
            
        so_number = f"SO-{data['inv']['no']}"
        
        # Default accounts configuration for Polycab Fan
        default_accounts = {
            "account_id": "1094368000035080815",
            "purchase_account_id": "1094368000035990257",
            "inventory_account_id": "1094368000035130337"
        }
        
        # 3. Resolve line items
        line_items = []
        for idx, item in enumerate(data['items']):
            sku = item.get("sku")
            name = item.get("name")
            qty = float(item.get("qty", 0))
            rate = float(item.get("rate", 0))
            
            if not sku or not name:
                continue
                
            # Search item in Zoho Books
            res = self.client.items.list(params={"sku": sku})
            items_list = res.get("items", [])
            
            if items_list:
                item_obj = items_list[0]
                item_id = item_obj.get("item_id")
                item_name = item_obj.get("name")
            else:
                if not create_missing_items:
                    raise ValueError(f"Item with SKU '{sku}' not found in Zoho Books. Use create_missing_items=True to allow automatic creation.")
                # Determine HSN
                sku_upper = sku.upper()
                name_upper = name.upper()
                hsn = "8516" if ("HEATER" in name_upper or "HWH" in sku_upper) else "8414"
                
                # Create item
                item_payload = {
                    "name": name,
                    "sku": sku,
                    "hsn_or_sac": hsn,
                    "rate": rate,
                    "purchase_rate": round(rate / 1.12, 2),
                    "account_id": default_accounts["account_id"],
                    "purchase_account_id": default_accounts["purchase_account_id"],
                    "inventory_account_id": default_accounts["inventory_account_id"],
                    "item_tax_preferences": [{"tax_name": "GST18", "tax_percentage": 18}],
                    "is_taxable": True,
                    "product_type": "goods",
                    "unit": "NOS",
                    "track_inventory": True,
                    "inventory_valuation_method": "fifo",
                    "can_be_sold": True,
                    "can_be_purchased": True
                }
                new_item_res = self.client.items.create(item_payload)
                new_item = new_item_res.get("item", {})
                item_id = new_item.get("item_id")
                item_name = new_item.get("name")
                
            line_items.append({
                "item_id": item_id,
                "name": item_name,
                "quantity": qty,
                "rate": rate,
                "description": name
            })
            
        # 4. Create Sales Order
        so_payload = {
            "customer_id": customer_id,
            "salesorder_number": so_number,
            "reference_number": data['inv']['no'],
            "date": inv_date,
            "line_items": line_items,
            "notes": f"Generated automatically from invoice YAML {data['inv']['no']}"
        }
        
        try:
            return self.create(so_payload)
        except Exception as e:
            if "4097" in str(e) or "auto-generated number" in str(e):
                so_payload.pop("salesorder_number", None)
                return self.create(so_payload)
            raise

class CreditNotes(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'creditnotes')

class SalesReturns(BaseResource, StatusMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'salesreturns')

class CustomerPayments(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'customerpayments')
        
    def refund(self, payment_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', payment_id, 'refunds', data=data)
