import re
import logging
import calendar
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from ..base import BaseResource

logger = logging.getLogger("zoho_books")

# Regex to split document numbers into prefix and sequential integer
# Matches prefix and trailing digits
DOC_NO_PATTERN = re.compile(r'^(.*?)(0*[1-9]\d*|0+)$')

def parse_doc_number(doc_no: str) -> Tuple[str, int, int]:
    """
    Parses a document number into (prefix, sequence_integer, numeric_width).
    Example: 'SB2627INV-00005' -> ('SB2627INV-', 5, 5)
    If not matchable, returns (doc_no, 0, 0).
    """
    if not doc_no:
        return "", 0, 0
    doc_no_str = str(doc_no).strip()
    match = DOC_NO_PATTERN.match(doc_no_str)
    if match:
        prefix = match.group(1)
        num_str = match.group(2)
        return prefix, int(num_str), len(num_str)
    return doc_no_str, 0, 0

class GST(BaseResource):
    """
    Helper resource under ZohoBooksAPI to run GST validation checks.
    """
    def __init__(self, client: Any):
        super().__init__(client, 'gst')

    def get_month_date_range(self, month_str: str) -> Tuple[str, str]:
        """
        Parses a month string ('YYYY-MM') and returns ('YYYY-MM-01', 'YYYY-MM-DD').
        """
        try:
            dt = datetime.strptime(month_str.strip(), "%Y-%m")
            year = dt.year
            month = dt.month
            _, last_day = calendar.monthrange(year, month)
            return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"
        except ValueError as e:
            raise ValueError(f"Invalid month format '{month_str}'. Must be 'YYYY-MM'.") from e

    def validate_gst_data(self, month_str: str) -> Dict[str, Any]:
        """
        Executes outward GST validations:
        1. Checks invoice number sequence gaps and chronology.
        2. Checks credit note number sequence gaps and chronology.
        3. Lists draft and void documents.
        4. Summarizes HSN and GST rate-wise taxable value, tax, and total.
        """
        start_date, end_date = self.get_month_date_range(month_str)
        logger.info(f"Running GST validations for date range {start_date} to {end_date}...")
        
        # 1. Fetch Invoices and Credit Notes
        # We query the lists within the month
        params = {"date_start": start_date, "date_end": end_date}
        invoices = self.client.invoices.list_all(params=params)
        credit_notes = self.client.credit_notes.list_all(params=params)
        
        # 2. Run validations
        invoice_results = self._validate_document_sequence_and_status(
            invoices, 'invoice_number', 'invoice_id', 'date'
        )
        cn_results = self._validate_document_sequence_and_status(
            credit_notes, 'creditnote_number', 'creditnote_id', 'date'
        )
        
        # 3. Fetch detailed data for calculation (excluding draft/void)
        active_invoices = [inv for inv in invoices if inv.get('status') not in ('draft', 'void')]
        active_credit_notes = [cn for cn in credit_notes if cn.get('status') not in ('draft', 'void')]
        
        detailed_invoices = self._fetch_details_concurrently(
            self.client.invoices, active_invoices, 'invoice_id', 'invoice'
        )
        detailed_credit_notes = self._fetch_details_concurrently(
            self.client.credit_notes, active_credit_notes, 'creditnote_id', 'creditnote'
        )
        
        # 4. Generate HSN & GST% Tax Summary
        summary = self._generate_tax_summary(detailed_invoices, detailed_credit_notes)
        
        return {
            "month": month_str,
            "date_range": (start_date, end_date),
            "invoices": {
                "total_count": len(invoices),
                "active_count": len(active_invoices),
                "draft": invoice_results["draft"],
                "void": invoice_results["void"],
                "missing": invoice_results["missing"],
                "out_of_chronology": invoice_results["out_of_chronology"]
            },
            "credit_notes": {
                "total_count": len(credit_notes),
                "active_count": len(active_credit_notes),
                "draft": cn_results["draft"],
                "void": cn_results["void"],
                "missing": cn_results["missing"],
                "out_of_chronology": cn_results["out_of_chronology"]
            },
            "tax_summary": summary
        }

    def _validate_document_sequence_and_status(
        self, docs: List[Dict[str, Any]], num_key: str, id_key: str, date_key: str
    ) -> Dict[str, Any]:
        """
        Performs status classification and sequence/chronological order check on list of documents.
        """
        draft_docs = []
        void_docs = []
        conforming_docs = []
        
        for doc in docs:
            num = doc.get(num_key)
            status = doc.get('status', '').lower()
            doc_id = doc.get(id_key)
            date_val = doc.get(date_key, '')
            
            # 1. Check statuses
            info = {"id": doc_id, "number": num, "date": date_val, "status": doc.get('status')}
            if status == 'draft':
                draft_docs.append(info)
            elif status == 'void':
                void_docs.append(info)
                
            # Parse document number for sequence checking
            prefix, seq, width = parse_doc_number(num)
            if seq > 0:
                conforming_docs.append({
                    "doc": doc,
                    "number": num,
                    "date": date_val,
                    "prefix": prefix,
                    "seq": seq,
                    "width": width
                })
        
        # 2. Group by prefix
        groups = {}
        for item in conforming_docs:
            prefix = item["prefix"]
            groups.setdefault(prefix, []).append(item)
            
        missing_numbers = []
        out_of_chronology = []
        
        # 3. Analyze each prefix group
        for prefix, items in groups.items():
            # Sort by sequence number
            items.sort(key=lambda x: x["seq"])
            
            # Check for sequence gaps
            seqs_found = {x["seq"] for x in items}
            min_seq = min(seqs_found)
            max_seq = max(seqs_found)
            
            for s in range(min_seq, max_seq + 1):
                if s not in seqs_found:
                    # Determine formatting width (using first item's width or default)
                    width = items[0]["width"]
                    missing_num = f"{prefix}{s:0{width}d}"
                    missing_numbers.append(missing_num)
            
            # Check for chronological order violation
            # The dates should be non-decreasing when sorted by sequence number
            for idx in range(1, len(items)):
                prev_item = items[idx - 1]
                curr_item = items[idx]
                
                prev_date = prev_item["date"]
                curr_date = curr_item["date"]
                
                if curr_date < prev_date:
                    out_of_chronology.append({
                        "number": curr_item["number"],
                        "date": curr_date,
                        "preceded_by": prev_item["number"],
                        "preceding_date": prev_date,
                        "message": f"Document {curr_item['number']} (Date: {curr_date}) is dated earlier than preceding document {prev_item['number']} (Date: {prev_date}) in sequence."
                    })
                    
        return {
            "draft": draft_docs,
            "void": void_docs,
            "missing": sorted(missing_numbers),
            "out_of_chronology": out_of_chronology
        }

    def _fetch_details_concurrently(
        self, client_module: Any, docs: List[Dict[str, Any]], id_key: str, doc_key: str
    ) -> List[Dict[str, Any]]:
        """
        Fetches full document details concurrently using ThreadPoolExecutor.
        """
        if not docs:
            return []
            
        def fetch_one(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            doc_id = doc.get(id_key)
            if not doc_id:
                return None
            try:
                res = client_module.get(doc_id)
                return res.get(doc_key)
            except Exception as e:
                logger.error(f"Failed to fetch full details for {doc_key} {doc_id}: {e}")
                return None

        # Fetch using up to 10 threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_one, docs))
            
        return [r for r in results if r is not None]

    def _generate_tax_summary(
        self, detailed_invoices: List[Dict[str, Any]], detailed_credit_notes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregates taxable value, tax, and totals grouped by HSN and GST rate.
        Generates separate sums for Invoices, Credit Notes, and Net Consolidated.
        """
        def init_agg():
            return {"taxable": 0.0, "tax": 0.0, "total": 0.0}

        inv_agg = {}
        cn_agg = {}
        net_agg = {}

        # Aggregate invoices
        for inv in detailed_invoices:
            for item in inv.get('line_items', []):
                hsn = item.get('hsn_or_sac')
                if not hsn:
                    hsn = "N/A"
                hsn = str(hsn).strip()
                gst_pct = float(item.get('tax_percentage', 0))
                
                key = (hsn, gst_pct)
                taxable = float(item.get('item_total', 0.0))
                tax_val = sum(float(tax.get('tax_amount', 0.0)) for tax in item.get('line_item_taxes', []))
                
                # Update Invoice Aggregation
                inv_agg.setdefault(key, init_agg())
                inv_agg[key]["taxable"] += taxable
                inv_agg[key]["tax"] += tax_val
                inv_agg[key]["total"] += (taxable + tax_val)

                # Update Net Aggregation
                net_agg.setdefault(key, init_agg())
                net_agg[key]["taxable"] += taxable
                net_agg[key]["tax"] += tax_val
                net_agg[key]["total"] += (taxable + tax_val)

        # Aggregate credit notes
        for cn in detailed_credit_notes:
            for item in cn.get('line_items', []):
                hsn = item.get('hsn_or_sac')
                if not hsn:
                    hsn = "N/A"
                hsn = str(hsn).strip()
                gst_pct = float(item.get('tax_percentage', 0))
                
                key = (hsn, gst_pct)
                taxable = float(item.get('item_total', 0.0))
                tax_val = sum(float(tax.get('tax_amount', 0.0)) for tax in item.get('line_item_taxes', []))
                
                # Update CN Aggregation
                cn_agg.setdefault(key, init_agg())
                cn_agg[key]["taxable"] += taxable
                cn_agg[key]["tax"] += tax_val
                cn_agg[key]["total"] += (taxable + tax_val)

                # Update Net Aggregation (Subtract Credit Notes)
                net_agg.setdefault(key, init_agg())
                net_agg[key]["taxable"] -= taxable
                net_agg[key]["tax"] -= tax_val
                net_agg[key]["total"] -= (taxable + tax_val)

        # Helper to format dict keys and round values
        def finalize_summary(agg):
            final = []
            for (hsn, gst), vals in sorted(agg.items(), key=lambda x: (x[0][0], x[0][1])):
                final.append({
                    "hsn_or_sac": hsn,
                    "gst_percentage": gst,
                    "taxable_value": round(vals["taxable"], 2),
                    "tax_amount": round(vals["tax"], 2),
                    "total": round(vals["total"], 2)
                })
            return final

        return {
            "invoices": finalize_summary(inv_agg),
            "credit_notes": finalize_summary(cn_agg),
            "consolidated": finalize_summary(net_agg)
        }
