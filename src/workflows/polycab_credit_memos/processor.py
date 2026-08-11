import os
import re
import pdfplumber
import logging
from datetime import datetime
from typing import Any, Dict, Optional, List
from ..core.config import Config
from ..vendor_ledger_reconciliation.matcher import fetch_vendor_credits

logger = logging.getLogger(__name__)

def parse_polycab_credit_memo(pdf_path: str) -> Dict[str, Any]:
    """
    Parses a Polycab credit memo PDF using pdfplumber and extracts Credit Note details:
      - Credit Note Number (AR Invoice Number)
      - Date (Invoice Date) formatted as YYYY-MM-DD
      - Total Amount (reconciled correctly for single and multi-page layouts)
      - Description (extracted from line items)
      - Raw text (to check for GST lines)
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")
        
    logger.info(f"Parsing credit memo PDF: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        all_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    if not all_text.strip():
        raise ValueError(f"No extractable text found in PDF: {pdf_path}")
        
    # 1. Credit Note Number (AR Invoice Number)
    cn_match = re.search(r"AR Invoice Number[ \t]*:[ \t]*(\d+)", all_text)
    cn_num = cn_match.group(1) if cn_match else None
    if not cn_num:
        basename = os.path.basename(pdf_path)
        name_match = re.search(r"CM-(\d+)", basename)
        if name_match:
            cn_num = name_match.group(1)
            
    # 2. Date
    date_match = re.search(r"(?<!Customer\s)(?<!Customer)Invoice Date[ \t]*:[ \t]*([\w\-]+)", all_text)
    raw_date = date_match.group(1) if date_match else None
    
    formatted_date = None
    if raw_date:
        parts = raw_date.split("-")
        if len(parts) == 3:
            day, month_str, year = parts
            months = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06", 
                      "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}
            month = months.get(month_str.upper())
            if not month:
                raise ValueError(f"Unsupported invoice month: {month_str!r}")
            year_format = "%y" if len(year) == 2 else "%Y"
            try:
                parsed_date = datetime.strptime(
                    f"{day.zfill(2)}-{month}-{year}",
                    f"%d-%m-{year_format}",
                )
            except ValueError as exc:
                raise ValueError(f"Invalid invoice date: {raw_date!r}") from exc
            formatted_date = parsed_date.strftime("%Y-%m-%d")
            
    # 3. Amount
    amount = 0.0
    total_match = re.search(r"\bTOTAL\s+([\d\.,]+)", all_text)
    if total_match:
        try:
            amount = float(total_match.group(1).replace(",", ""))
        except ValueError:
            pass
    else:
        # Scan backward from Rupees line
        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
        rupees_idx = -1
        for idx, l in enumerate(lines):
            if "rupees" in l.lower():
                rupees_idx = idx
                break
                
        if rupees_idx != -1:
            for offset in range(1, 6):
                idx = rupees_idx - offset
                if idx < 0:
                    break
                line = lines[idx]
                num_pattern = r"([\d\.,]+)\s+(\d+)\s+0\s+([\d\.,]+)\s+([\d\.,]+)"
                match = re.search(num_pattern, line)
                if match:
                    try:
                        amount = float(match.group(4).replace(",", ""))
                    except ValueError:
                        pass
                    break
                    
    # 4. Description
    description = ""
    lines = [l.strip() for l in all_text.split("\n") if l.strip()]
    rupees_idx = -1
    for idx, l in enumerate(lines):
        if "rupees" in l.lower():
            rupees_idx = idx
            break
            
    if rupees_idx != -1:
        desc_lines = []
        start_idx = 0
        for idx in range(rupees_idx - 1, -1, -1):
            if "hsn/sac" in lines[idx].lower() or "total value" in lines[idx].lower():
                start_idx = idx + 1
                break
        
        for idx in range(start_idx, rupees_idx):
            line = lines[idx]
            if line.strip().lower() in ["no", "no."]:
                continue
            num_pattern = r"([\d\.,]+)\s+(\d+)\s+0\s+([\d\.,]+)\s+([\d\.,]+)"
            match = re.search(num_pattern, line)
            if match:
                line = line[:match.start()].strip()
                if not line:
                    continue
            if line.startswith("1 ") or line == "1":
                line = line[2:].strip()
            desc_lines.append(line)
            
        description = " ".join(desc_lines).strip()
        description = re.sub(r"\s+", " ", description)
        
    if not description:
        description = f"Polycab Credit Note {cn_num or ''}"
        
    return {
        "vendor_name": "Polycab India Limited",
        "vendor_credit_number": cn_num,
        "date": formatted_date,
        "amount": amount,
        "description": description,
        "raw_text": all_text
    }

_VENDOR_CACHE = {}
_CHART_OF_ACCOUNTS_CACHE = None

def resolve_vendor_id(books_client: Any, name: str) -> Optional[str]:
    """Finds contact ID for a vendor by name in Zoho Books."""
    if name in _VENDOR_CACHE:
        return _VENDOR_CACHE[name]
    res = books_client.contacts.list(params={"contact_name": name})
    contacts = res.get("contacts", [])
    if contacts:
        vendor_id = contacts[0].get("contact_id")
        _VENDOR_CACHE[name] = vendor_id
        return vendor_id
    if "polycab" in name.lower():
        return Config.POLYCAB_VENDOR_ID
    return None

def resolve_account_id(books_client: Any, name: str) -> Optional[str]:
    """Finds account ID by name query in Zoho Books chart of accounts."""
    global _CHART_OF_ACCOUNTS_CACHE
    if _CHART_OF_ACCOUNTS_CACHE is None:
        res = books_client.chart_of_accounts.list()
        _CHART_OF_ACCOUNTS_CACHE = res.get("chartofaccounts", [])
    for a in _CHART_OF_ACCOUNTS_CACHE:
        if name.lower() in a.get("account_name", "").lower():
            return a.get("account_id")
    for a in _CHART_OF_ACCOUNTS_CACHE:
        if "purchase discounts" in a.get("account_name", "").lower():
            return a.get("account_id")
    return None


def resolve_item_id(pdf_text: str) -> str:
    """
    Classifies a credit memo as a Scheme CN or RSO CN based on raw PDF text.
    Returns the corresponding Zoho Books Item ID.

    RSO CN rule: 'RSO Number' field must contain a purely-numeric value.
    Adjacent PDF fields like 'E-Way Bill No' must NOT be matched.
    """
    text_lower = pdf_text.lower()

    # Only match if the value after 'RSO Number :' is a non-empty digit sequence.
    # Using \d+ (not \S+) prevents capturing adjacent field names like 'E-Way'.
    rso_match = re.search(r"RSO\s+(?:Number|No\.?)\s*:\s*(\d+)", pdf_text, re.IGNORECASE)
    if rso_match and rso_match.group(1).strip():
        logger.info(f"Classified CN as RSO CN based on RSO Number: '{rso_match.group(1)}'")
        return Config.ZOHO_RSO_CN_ITEM_ID

    if "return type without reference" in text_lower or "ldo01" in text_lower or "llp01" in text_lower:
        return Config.ZOHO_RSO_CN_ITEM_ID
    return Config.ZOHO_SCHEME_CN_ITEM_ID

def resolve_bill_id_by_number(books_client: Any, vendor_id: str, bill_number: str) -> Optional[str]:
    """Finds the bill ID for a specific bill number under this vendor in Zoho Books."""
    res = books_client.bills.list(params={"vendor_id": vendor_id, "bill_number": bill_number})
    bills = res.get("bills", [])
    if bills:
        return bills[0].get("bill_id")
    return None

def resolve_tax_id(books_client: Any, pdf_text: str) -> str:
    """
    Determines the correct GST tax group ID in Zoho Books based on PDF text.
    Almost all credit notes are commercial/accounting CN, so we always return GST0 (no tax).
    """
    return Config.ZOHO_GST0_TAX_ID

def create_vendor_credit_from_pdf(
    books_client: Any, 
    pdf_path: str, 
    vendor_name: str = "Polycab",
    account_name: str = "Polycab Scheme - Expense",
    vendor_id: Optional[str] = None,
    location_id: str = Config.EXPECTED_LOCATION_ID,
) -> Dict[str, Any]:
    """
    Parses PDF and posts a new Vendor Credit transaction to Zoho Books.
    Omit bill_id and uses registered invoice type unless explicitly given. Sets GST Out of Scope.
    """
    details = parse_polycab_credit_memo(pdf_path)
    
    vendor_id = vendor_id or resolve_vendor_id(books_client, vendor_name)
    if not vendor_id:
        raise ValueError(f"Could not resolve vendor ID for name: '{vendor_name}'")
        
    bill_number_match = re.search(r'Original Tax Inv\.\s*No\.[ \t]*:[ \t]*([^\s\r\n]+)', details["raw_text"])
    bill_number = bill_number_match.group(1) if bill_number_match else None
    
    bill_id = None
    if bill_number:
        bill_id = resolve_bill_id_by_number(books_client, vendor_id, bill_number)
        
    item_id = resolve_item_id(details["raw_text"])
    account_id = resolve_account_id(books_client, account_name)
    if not account_id:
        raise ValueError(f"Could not resolve account ID for name: '{account_name}'")
    
    # If it is an RSO CN, use the RSO number alone as description
    description = details["description"]
    if item_id == Config.ZOHO_RSO_CN_ITEM_ID:
        rso_match = re.search(r"RSO\s+(?:Number|No\.?)\s*:\s*(\d+)", details["raw_text"], re.IGNORECASE)
        if rso_match:
            description = rso_match.group(1).strip()
    
    payload = {
        "vendor_id": vendor_id,
        "location_id": location_id,
        "vendor_credit_number": details["vendor_credit_number"],
        "date": details["date"],
        "line_items": [
            {
                "item_id": item_id,
                "account_id": account_id,
                "rate": details["amount"],
                "quantity": 1,
                "description": description,
                "gst_treatment_code": "out_of_scope"
            }
        ]
    }
    
    if bill_id:
        payload["bill_id"] = bill_id
    else:
        payload["reference_invoice_type"] = "registered"
    
    res = books_client.vendor_credits.create(payload)
    return res.get("vendor_credit", res.get("vendorcredit", res))

def upload_vendor_credit_attachment(books_client: Any, vendor_credit_id: str, pdf_path: str) -> Dict[str, Any]:
    """Attaches PDF file to a Vendor Credit in Zoho Books."""
    return books_client.vendor_credits.add_attachment(vendor_credit_id, pdf_path)

def upload_to_workdrive(wd_client: Any, folder_id: str, pdf_path: str) -> Dict[str, Any]:
    """Uploads PDF file to Zoho WorkDrive folder."""
    return wd_client.files.upload(folder_id, pdf_path)

def process_polycab_credit_memos(
    books_client: Optional[Any] = None,
    wd_client: Optional[Any] = None,
    files_dir: str = Config.FILES_DIR,
    folder_id: str = Config.POLYCAB_FOLDER_ID,
    vendor_id: str = Config.POLYCAB_VENDOR_ID,
    location_id: str = Config.EXPECTED_LOCATION_ID,
) -> Dict[str, Any]:
    """
    Processes all Polycab credit memo PDFs in the files_dir.
    Creates vendor credits in Zoho Books and uploads the PDFs to WorkDrive.
    Matches credit numbers to prevent duplicate postings.
    
    Args:
        books_client (Any, optional): ZohoBooksAPI client instance. Auto-initialized if None.
        wd_client (Any, optional): ZohoWorkdriveAPI client instance. Auto-initialized if None.
        files_dir (str): Directory containing credit memo PDFs.
        folder_id (str): Target Zoho WorkDrive folder ID.
        vendor_id (str): Vendor ID for Polycab.
        location_id (str): Zoho Books location / branch ID for created credits.
        
    Returns:
        Dict[str, Any]: Detailed counts of processed, created, uploaded, and skipped items.
    """
    if not books_client or not wd_client:
        from ..core.auth import get_books_client, get_workdrive_client, fetch_access_tokens
        tokens = fetch_access_tokens()
        if not books_client:
            books_client = get_books_client(token=tokens.get("books"))
        if not wd_client:
            wd_client = get_workdrive_client(token=tokens.get("workdrive"))
    # 1. Fetch existing vendor credits in Zoho Books to prevent duplicates
    logger.info("Fetching existing vendor credits in Zoho Books...")
    existing_credits = fetch_vendor_credits(books_client, {"vendor_id": vendor_id})
    existing_credit_numbers = {c.get("vendor_credit_number") for c in existing_credits if c.get("vendor_credit_number")}
    logger.info(f"Found {len(existing_credit_numbers)} existing vendor credits in Books.")
    
    # 2. Fetch existing files in WorkDrive target folder to prevent duplicate uploads
    logger.info("Fetching existing files in Zoho WorkDrive folder...")
    try:
        wd_files = wd_client.files.list_all_files(folder_id)
        existing_wd_filenames = {f.get("attributes", {}).get("name") for f in wd_files}
    except Exception as e:
        raise RuntimeError(
            "Could not verify existing WorkDrive files; refusing to upload because "
            "duplicate protection is unavailable."
        ) from e
    logger.info(f"Found {len(existing_wd_filenames)} files in target WorkDrive folder.")

    # Get all PDF files to process
    if not os.path.exists(files_dir):
        raise FileNotFoundError(f"Files directory not found: {files_dir}")
        
    pdf_files = sorted([f for f in os.listdir(files_dir) if f.endswith(".pdf") and (f.startswith("CM-") or f.startswith("CN-"))])
    if not pdf_files:
        logger.info(f"No CM- or CN- PDF files found in {files_dir} folder.")
        return {
            "total_files": 0,
            "processed": 0,
            "books_created": 0,
            "books_skipped": 0,
            "wd_uploaded": 0,
            "wd_skipped": 0,
            "errors": 0
        }
        
    logger.info(f"Processing {len(pdf_files)} PDF credit memos...")
    
    summary = {
        "total_files": len(pdf_files),
        "processed": 0,
        "books_created": 0,
        "books_skipped": 0,
        "wd_uploaded": 0,
        "wd_skipped": 0,
        "errors": 0
    }
    
    for f in pdf_files:
        file_path = os.path.join(files_dir, f)
        logger.info(f"--------------------------------------------------")
        logger.info(f"File: {f}")
        
        try:
            # Step 1: Parse PDF
            details = parse_polycab_credit_memo(file_path)
            cn_num = details["vendor_credit_number"]
            amount = details["amount"]
            date_str = details["date"]
            
            logger.info(f"Parsed details: CN={cn_num} | Date={date_str} | Amount={amount}")
            summary["processed"] += 1
            
            if not cn_num or amount <= 0:
                logger.error("Invalid details parsed. Skipping.")
                summary["errors"] += 1
                continue
                
            # Step 2: Create Vendor Credit in Zoho Books
            vc_id = None
            credit_created = False
            if cn_num in existing_credit_numbers:
                logger.info(f"Vendor credit {cn_num} already exists in Zoho Books. Skipping creation.")
                summary["books_skipped"] += 1
                for c in existing_credits:
                    if c.get("vendor_credit_number") == cn_num:
                        vc_id = c.get("vendor_credit_id")
                        break
            else:
                logger.info("Creating vendor credit in Zoho Books...")
                vc = create_vendor_credit_from_pdf(
                    books_client,
                    file_path,
                    vendor_id=vendor_id,
                    location_id=location_id,
                )
                vc_id = vc.get("vendor_credit_id")
                logger.info(f"Vendor credit successfully created in Books (ID: {vc_id}).")
                summary["books_created"] += 1
                credit_created = True
                existing_credit_numbers.add(cn_num)
                
            # Step 3: Attach PDF in Zoho Books
            if vc_id and credit_created:
                try:
                    logger.info("Attaching PDF to vendor credit in Books...")
                    upload_vendor_credit_attachment(books_client, vc_id, file_path)
                    logger.info("PDF attached to vendor credit successfully.")
                except Exception as e:
                    logger.warning(f"Could not attach PDF to Zoho Books: {e}")
            
            # Step 4: Upload to WorkDrive
            if f in existing_wd_filenames:
                logger.info("File already exists in Zoho WorkDrive folder. Skipping upload.")
                summary["wd_skipped"] += 1
            else:
                logger.info("Uploading file to Zoho WorkDrive...")
                upload_to_workdrive(wd_client, folder_id, file_path)
                logger.info("File successfully uploaded to WorkDrive.")
                summary["wd_uploaded"] += 1
                existing_wd_filenames.add(f)
                
        except Exception as e:
            logger.error(f"Error processing file {f}: {e}")
            summary["errors"] += 1
            
    return summary

def check_vendor_credits_location(
    books_client: Optional[Any] = None,
    vendor_id: str = Config.POLYCAB_VENDOR_ID,
    expected_location_id: str = Config.EXPECTED_LOCATION_ID
) -> Dict[str, Any]:
    """
    Fetches all vendor credits for a vendor and audits them to find ones with incorrect
    location/branch ID or no location set.
    
    Args:
        books_client (Any, optional): ZohoBooksAPI client instance. Auto-initialized if None.
        vendor_id (str): Vendor ID to audit.
        expected_location_id (str): Expected Location / Branch ID.
        
    Returns:
        Dict[str, Any]: Categorized credit notes (correct, mismatched, no_location) and totals.
    """
    if not books_client:
        from ..core.auth import get_books_client
        books_client = get_books_client()

    logger.info(f"Fetching ALL vendor credits for vendor_id={vendor_id}...")
    
    all_credits = books_client.vendor_credits.list_all(
        params={"vendor_id": vendor_id},
        resource_key="vendor_credits",
    )
    logger.info("Fetched %s vendor credits.", len(all_credits))
        
    mismatched = []
    no_location = []
    correct = []
    
    for vc in all_credits:
        loc_id = vc.get('location_id') or vc.get('branch_id') or ''
        loc_name = vc.get('location_name') or vc.get('branch_name') or ''
        vc_number = vc.get('vendor_credit_number', '')
        vc_id = vc.get('vendor_credit_id', '')
        date = vc.get('date', '')
        amount = vc.get('total', vc.get('amount', ''))
        status = vc.get('status', '')
        
        info = {
            'id': vc_id,
            'number': vc_number,
            'date': date,
            'amount': amount,
            'status': status,
            'location_id': loc_id,
            'location_name': loc_name
        }
        
        if not loc_id:
            no_location.append(info)
        elif loc_id != expected_location_id:
            mismatched.append(info)
        else:
            correct.append(info)
            
    return {
        "correct": correct,
        "mismatched": mismatched,
        "no_location": no_location,
        "total_checked": len(all_credits)
    }
