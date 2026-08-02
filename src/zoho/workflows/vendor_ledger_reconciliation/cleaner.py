import xlrd
import csv
import os
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from ..core.config import Config
from ..core.exceptions import LedgerParsingError, LedgerNotImplementedError

logger = logging.getLogger(__name__)

def get_ledger_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extracts metadata (Start Date, End Date) from a ledger file.
    Supports:
      - Polycab Excel (.xls): reads dedicated header rows.
      - Zeiss CSV (.csv):     derives date range from the data rows.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    filename = os.path.basename(file_path).lower()

    # ── CSV path (Zeiss and future CSV vendors) ─────────────────────────────
    if filename.endswith(".csv"):
        dates = []
        with open(file_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw = (row.get("Posting Date") or "").strip()
                if not raw:
                    continue
                try:
                    dates.append(datetime.strptime(raw, "%d.%m.%Y").date())
                except ValueError:
                    pass
        return {
            "start_date": min(dates).isoformat() if dates else None,
            "end_date":   max(dates).isoformat() if dates else None,
            "party_name": None,
            "opening_balance": 0.0,
        }

    # ── Excel path (Polycab .xls) ────────────────────────────────────────────
    workbook = xlrd.open_workbook(file_path)
    sheet = workbook.sheet_by_index(0)
    metadata = {
        "start_date": None,
        "end_date": None,
        "party_name": None,
        "opening_balance": 0.0
    }

    for r in range(min(15, sheet.nrows)):
        row = [str(sheet.cell_value(r, c)).strip() for c in range(min(sheet.ncols, 5))]
        if not row:
            continue
        first_val = row[0].lower()
        if "start date" in first_val:
            metadata["start_date"] = row[2] if len(row) > 2 else None
        elif "end date" in first_val:
            metadata["end_date"] = row[2] if len(row) > 2 else None
        elif "party name" in first_val:
            metadata["party_name"] = row[2] if len(row) > 2 else None
        elif "opening balance" in first_val:
            try:
                metadata["opening_balance"] = float(sheet.cell_value(r, 2))
            except Exception:
                pass
    return metadata

def clean_polycab_ledger(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses and cleans Polycab's reconciliation ledger Excel file (.xls).
    """
    workbook = xlrd.open_workbook(file_path)
    sheet = workbook.sheet_by_index(0)
    
    header_row_index = -1
    for r in range(sheet.nrows):
        val = sheet.cell_value(r, 0)
        if str(val).strip().lower() == "account no":
            header_row_index = r
            break
            
    if header_row_index == -1:
        raise LedgerParsingError("Could not find the Polycab header row starting with 'Account No'")
        
    headers = [str(sheet.cell_value(header_row_index, c)).strip() for c in range(sheet.ncols)]
    
    key_mapping = {
        "account no": "account_no",
        "account name": "account_name",
        "ar invoice date": "date",
        "document type": "document_type",
        "transaction no": "transaction_no",
        "transaction reference": "transaction_reference",
        "customer po no.": "customer_po_no",
        "debit amount": "debit_amount",
        "credit amount": "credit_amount",
        "closing balance": "closing_balance"
    }
    
    col_to_key = {}
    for idx, h in enumerate(headers):
        h_lower = h.lower()
        if h_lower in key_mapping:
            col_to_key[idx] = key_mapping[h_lower]
            
    transactions = []
    for r in range(header_row_index + 1, sheet.nrows):
        first_val = str(sheet.cell_value(r, 0)).strip()
        row_vals = [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
        
        if not any(row_vals):
            continue
            
        is_summary = False
        for val in row_vals:
            if val in ("Opening Balance", "Total Debit Amount", "Total Credit Amount", "Closing Balance"):
                is_summary = True
                break
        if is_summary:
            continue
            
        if not first_val:
            continue
            
        tx = {}
        for c, key in col_to_key.items():
            cell = sheet.cell(r, c)
            val = cell.value
            
            if key == "date":
                if cell.ctype == xlrd.XL_CELL_DATE:
                    dt = xlrd.xldate_as_datetime(val, workbook.datemode)
                    tx[key] = dt.date().isoformat()
                else:
                    tx[key] = str(val).strip()
            elif key in ("debit_amount", "credit_amount", "closing_balance"):
                try:
                    tx[key] = float(val) if val != "" else 0.0
                except (ValueError, TypeError):
                    tx[key] = 0.0
            elif key in ("account_no", "transaction_no"):
                if isinstance(val, float):
                    if val.is_integer():
                        tx[key] = str(int(val))
                    else:
                        tx[key] = str(val)
                else:
                    tx[key] = str(val).strip()
            else:
                tx[key] = str(val).strip()
                
        if tx.get("transaction_no") and tx.get("date"):
            transactions.append(tx)
            
    return transactions

def clean_zeiss_ledger(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses and cleans Carl Zeiss India's CSV statement.

    Expected columns:
        Posting Date, Document No, Invoice Number, Due Date,
        Voucher Type, Debit, Credit, Closing Balance

    Voucher Type mapping:
        Invoice      -> sales invoice  (debit_amount)
        Credit Note  -> credit memo    (credit_amount)
        Receipts     -> receipt        (credit_amount)
    """
    VOUCHER_MAP = {
        "invoice":     "sales invoice",
        "credit note": "credit memo",
        "receipts":    "receipt",
    }

    transactions = []
    with open(file_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_date  = (row.get("Posting Date") or "").strip()
            doc_no    = (row.get("Document No")   or "").strip()
            inv_no    = (row.get("Invoice Number") or "").strip()
            vtype_raw = (row.get("Voucher Type")  or "").strip().lower()
            raw_debit = (row.get("Debit")         or "0").strip()
            raw_credit= (row.get("Credit")        or "0").strip()

            if not raw_date or not doc_no:
                continue

            # Parse DD.MM.YYYY -> YYYY-MM-DD
            try:
                parsed_date = datetime.strptime(raw_date, "%d.%m.%Y").date().isoformat()
            except ValueError:
                logger.warning(f"Zeiss cleaner: unrecognised date '{raw_date}' – skipping row")
                continue

            doc_type = VOUCHER_MAP.get(vtype_raw)
            if not doc_type:
                logger.debug(f"Zeiss cleaner: unknown voucher type '{vtype_raw}' – skipping row")
                continue

            try:
                debit_amount  = float(raw_debit.replace(",", ""))  if raw_debit  else 0.0
            except ValueError:
                debit_amount  = 0.0
            try:
                credit_amount = float(raw_credit.replace(",", "")) if raw_credit else 0.0
            except ValueError:
                credit_amount = 0.0

            # Reference mapping based on Voucher Type:
            if doc_type == "sales invoice":
                # For invoices -> use Invoice number column
                tx_no = inv_no or doc_no
                tx_ref = doc_no if inv_no else ""
            elif doc_type == "credit memo":
                # For credit notes -> use document number column
                tx_no = doc_no or inv_no
                tx_ref = inv_no if doc_no else ""
            elif doc_type == "receipt":
                # For receipts -> use amount
                amt_val = credit_amount if credit_amount > 0.0 else debit_amount
                tx_no = f"{amt_val:.2f}"
                tx_ref = inv_no or doc_no
            else:
                tx_no = inv_no or doc_no
                tx_ref = doc_no if inv_no else ""

            transactions.append({
                "date":                parsed_date,
                "document_type":       doc_type,
                "transaction_no":      tx_no,
                "transaction_reference": tx_ref,
                "debit_amount":        debit_amount,
                "credit_amount":       credit_amount,
            })

    # Net out and nullify receipt entries to resolve debit/credit reversals
    other_txs = [t for t in transactions if t["document_type"] != "receipt"]
    receipts = [t for t in transactions if t["document_type"] == "receipt"]

    cleaned_receipts = []
    for r in receipts:
        net_credit = r["credit_amount"] - r["debit_amount"]
        if net_credit > 0.0:
            r["credit_amount"] = net_credit
            r["debit_amount"] = 0.0
            cleaned_receipts.append(r)
        elif net_credit < 0.0:
            r["credit_amount"] = 0.0
            r["debit_amount"] = abs(net_credit)
            cleaned_receipts.append(r)
        else:
            logger.info(f"Zeiss cleaner: receipt nullified itself (net zero): {r['transaction_reference']}")

    # Cross-nullify debit reversals with corresponding credit receipts
    skipped_indices = set()
    for idx, r in enumerate(cleaned_receipts):
        if idx in skipped_indices:
            continue
        if r["debit_amount"] > 0.0:
            # Debit receipt (reversal). Find a credit receipt with matching amount and reference
            match_idx = -1
            for jdx, other in enumerate(cleaned_receipts):
                if jdx == idx or jdx in skipped_indices:
                    continue
                if other["credit_amount"] == r["debit_amount"]:
                    if other["transaction_reference"] == r["transaction_reference"]:
                        match_idx = jdx
                        break
            if match_idx != -1:
                logger.info(f"Zeiss cleaner: cross-nullified debit receipt {r['transaction_reference']} with credit receipt {cleaned_receipts[match_idx]['transaction_reference']}")
                skipped_indices.add(idx)
                skipped_indices.add(match_idx)

    # Rebuild final list, keeping only active credit receipts (exclude matched reversals/debit leftovers)
    final_receipts = [r for idx, r in enumerate(cleaned_receipts) if idx not in skipped_indices and r["credit_amount"] > 0.0]

    transactions = other_txs + final_receipts
    logger.info(f"Zeiss cleaner: parsed {len(transactions)} rows from {os.path.basename(file_path)}")
    return transactions

def clean_ledger_file(file_path: str, vendor_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Cleans a vendor or bank ledger file using the appropriate vendor-specific cleaner.
    
    Args:
        file_path (str): Path to the ledger file.
        vendor_key (str, optional): Key identifying the vendor/bank layout (e.g. 'polycab').
                                    If not specified, determined automatically from filename.
                                    
    Returns:
        List[Dict[str, Any]]: List of cleaned transaction dictionaries.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    filename = os.path.basename(file_path).lower()

    # Auto-detect vendor if not specified
    if not vendor_key:
        if filename.startswith("277498") or "polycab" in filename:
            vendor_key = "polycab"
        elif "zeiss" in filename:
            vendor_key = "zeiss"
        else:
            raise LedgerParsingError(f"Could not auto-determine vendor layout for file: {filename}. Please specify vendor_key.")

    if vendor_key == "polycab":
        entries = clean_polycab_ledger(file_path)
    elif vendor_key == "zeiss":
        entries = clean_zeiss_ledger(file_path)
    else:
        raise LedgerNotImplementedError(f"No cleaning implementation available for vendor key: '{vendor_key}'")

    for idx, entry in enumerate(entries):
        if "id" not in entry:
            entry["id"] = f"{vendor_key}_{idx}"

    return entries
