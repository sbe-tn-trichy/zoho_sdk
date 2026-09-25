"""GSTR-2 / GSTR-2B verification and cross-checking workflow against Zoho Books."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from zoho.helpers import get_month_range, parse_date
from zoho.helpers.gst import normalize_gstin

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AggregatePurchaseMapping:
    """Approved many-to-one portal invoices represented by one Books bill."""

    month: str
    bill_id: str
    bill_number: str
    portal_doc_type: str
    portal_doc_date: str
    portal_doc_number_pattern: str
    supplier_gstins: tuple[str, ...]
    expected_count: int
    expected_taxable: float
    expected_tax: float
    expected_total: float


@dataclass(frozen=True)
class GSTR2VerificationConfig:
    """Configuration settings for GSTR-2/2B verification."""

    amount_tolerance: float = 1.0  # Allowed difference in Rupees (rounding)
    include_drafts: bool = False
    fiscal_year_start_month: int = 4
    aggregate_mappings: tuple[AggregatePurchaseMapping, ...] = ()
    location_gstin_map: Mapping[str, Sequence[str]] = field(default_factory=dict)


def normalize_doc_number(value: Any) -> str:
    """
    Normalize document/invoice number for matching.
    Strips non-alphanumerics, converts to uppercase, and strips leading zeros.
    Example: '25-26/IC000092' -> '2526IC92', 'CDT2509931869534' -> 'CDT2509931869534'
    """
    if value is None:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value).strip()).upper()
    return cleaned.lstrip("0") or ("0" if cleaned else "")


def _to_float(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_portal_date(date_str: Any) -> Optional[date]:
    """Parse GST portal date in DD-MM-YYYY or YYYY-MM-DD format."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return parse_date(s)


class GSTR2Verifier:
    """Cross-checks GSTR-2/2B JSON returns against Zoho Books purchases."""

    def __init__(
        self,
        books_client: Any,
        config: Optional[GSTR2VerificationConfig] = None,
    ):
        self.books = books_client
        self.config = config or GSTR2VerificationConfig()
        self._cached_bills: Optional[List[Dict[str, Any]]] = None
        self._expense_cache: Dict[str, Mapping[str, Any]] = {}
        self._vendor_credit_cache: Dict[str, Mapping[str, Any]] = {}

    @staticmethod
    def _books_net_taxable(document: Mapping[str, Any]) -> Optional[float]:
        """Return taxable subtotal after an entity-level, pre-tax discount."""
        subtotal = document.get("sub_total")
        if subtotal in (None, ""):
            return None
        taxable = _to_float(subtotal)
        if (document.get("discount_type") == "entity_level"
                and document.get("is_discount_before_tax") is True):
            discount = document.get("discount_total")
            if discount in (None, ""):
                discount = document.get("discount_amount")
            taxable -= _to_float(discount)
        return round(taxable, 2)

    def run(
        self,
        gstr2_source: str | Path | Mapping[str, Any],
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute full cross-check of GSTR-2/2B data against Zoho Books.

        :param gstr2_source: Path to JSON file or parsed dictionary.
        :param month: Return month 'YYYY-MM'. If None, derived from JSON 'rtnprd'.
        :return: Comprehensive verification report dictionary.
        """
        raw_json = self._load_json(gstr2_source)
        portal_data = raw_json.get("data", raw_json)

        # 1. Parse portal metadata and period
        rtnprd = str(portal_data.get("rtnprd") or "").strip()
        recipient_gstin = str(portal_data.get("gstin") or "").strip().upper()
        generation_date = str(portal_data.get("gendt") or "").strip()

        # Derive target month 'YYYY-MM'
        target_month = month
        if not target_month and rtnprd and len(rtnprd) == 6:
            # e.g., '042025' -> '2025-04'
            target_month = f"{rtnprd[2:6]}-{rtnprd[0:2]}"
        if not target_month:
            target_month = date.today().strftime("%Y-%m")

        start_date, end_date = get_month_range(target_month)

        # 2. Parse GSTR-2B documents
        gstr2_docs = self._parse_portal_documents(portal_data)
        itc_summary_portal = portal_data.get("itcsumm", {})

        # 3. Fetch Zoho Books bills, GST-bearing expenses, and vendor credits
        fetch_errors: List[Dict[str, str]] = []
        if not recipient_gstin:
            fetch_errors.append({"source": "locations", "error": "Portal recipient GSTIN is missing"})
        location_gstins = self._configured_location_gstins(fetch_errors)
        books_bills = self._fetch_books_bills(
            start_date, end_date, fetch_errors, location_gstins, recipient_gstin,
        )
        books_expenses = self._fetch_books_expenses(
            start_date, end_date, fetch_errors, location_gstins, recipient_gstin,
            rcm_doc_numbers={
                doc["norm_number"] for doc in gstr2_docs if doc["reverse_charge"]
            },
        )
        books_credits = self._fetch_books_vendor_credits(
            start_date, end_date, fetch_errors, location_gstins, recipient_gstin,
        )

        # 4. Perform Matching & Classification
        reconciliation = self._reconcile(
            gstr2_docs=gstr2_docs,
            books_bills=books_bills,
            books_expenses=books_expenses,
            books_credits=books_credits,
            target_month=target_month,
        )

        return {
            "metadata": {
                "target_month": target_month,
                "return_period": rtnprd,
                "recipient_gstin": recipient_gstin,
                "included_locations": [
                    {"location_id": location_id}
                    for location_id, location in location_gstins.items()
                    if location["gstin"] == recipient_gstin
                ],
                "portal_generation_date": generation_date,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "config": {
                    "amount_tolerance": self.config.amount_tolerance,
                    "include_drafts": self.config.include_drafts,
                },
            },
            "portal_itc_summary": itc_summary_portal,
            "reconciliation": reconciliation,
            "fetch_errors": fetch_errors,
        }

    @staticmethod
    def _load_json(source: str | Path | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(source, Mapping):
            return source
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"GSTR-2 file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _parse_portal_documents(self, portal_data: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Parse b2b and cdnr documents from GSTR-2B JSON."""
        docdata = portal_data.get("docdata", {})
        documents: List[Dict[str, Any]] = []

        # 1. B2B Invoices
        for supplier in docdata.get("b2b", []):
            ctin = normalize_gstin(supplier.get("ctin"))
            trdnm = str(supplier.get("trdnm") or supplier.get("cname") or "").strip()
            supfildt = supplier.get("supfildt")
            supprd = supplier.get("supprd")

            for inv in supplier.get("inv", []):
                doc_num = str(inv.get("inum") or "").strip()
                doc_date = _parse_portal_date(inv.get("dt"))
                val = _to_float(inv.get("val"))
                txval = _to_float(inv.get("txval"))
                igst = _to_float(inv.get("igst"))
                cgst = _to_float(inv.get("cgst"))
                sgst = _to_float(inv.get("sgst"))
                cess = _to_float(inv.get("cess"))
                tax_total = igst + cgst + sgst + cess

                # If txval was 0 at doc level, sum from items if present
                items = inv.get("items", [])
                if txval == 0.0 and items:
                    txval = sum(_to_float(it.get("txval")) for it in items)
                    if igst == 0.0:
                        igst = sum(_to_float(it.get("iamt")) for it in items)
                    if cgst == 0.0:
                        cgst = sum(_to_float(it.get("camt")) for it in items)
                    if sgst == 0.0:
                        sgst = sum(_to_float(it.get("samt")) for it in items)
                    if cess == 0.0:
                        cess = sum(_to_float(it.get("csamt")) for it in items)
                    tax_total = igst + cgst + sgst + cess

                documents.append({
                    "section": "B2B",
                    "doc_type": "invoice",
                    "doc_number": doc_num,
                    "norm_number": normalize_doc_number(doc_num),
                    "doc_date": doc_date.isoformat() if doc_date else str(inv.get("dt") or ""),
                    "parsed_date": doc_date,
                    "supplier_gstin": ctin,
                    "supplier_name": trdnm,
                    "total_value": val,
                    "taxable_value": txval,
                    "igst": igst,
                    "cgst": cgst,
                    "sgst": sgst,
                    "cess": cess,
                    "tax_total": tax_total,
                    "reverse_charge": str(inv.get("rev") or "N").upper() == "Y",
                    "itc_available": str(inv.get("itcavl") or "Y").upper() == "Y",
                    "itc_reason": inv.get("rsn") or "",
                    "source_type": inv.get("srctyp") or "",
                    "irn": inv.get("irn") or "",
                    "supplier_filing_date": supfildt,
                    "supplier_return_period": supprd,
                    "pos": inv.get("pos") or "",
                })

        # 2. CDNR Credit/Debit Notes
        for supplier in docdata.get("cdnr", []):
            ctin = normalize_gstin(supplier.get("ctin"))
            trdnm = str(supplier.get("trdnm") or supplier.get("cname") or "").strip()
            supfildt = supplier.get("supfildt")
            supprd = supplier.get("supprd")

            # Notes can be listed under 'nt' or 'inv'
            notes = supplier.get("nt", []) or supplier.get("inv", [])
            for note in notes:
                doc_num = str(note.get("ntnum") or note.get("nt_num") or "").strip()
                doc_date = _parse_portal_date(note.get("dt") or note.get("nt_dt"))
                nt_type = str(note.get("typ") or note.get("nttyp") or "C").upper()
                doc_type = "credit_note" if nt_type == "C" else "debit_note"

                val = _to_float(note.get("val"))
                txval = _to_float(note.get("txval"))
                igst = _to_float(note.get("igst"))
                cgst = _to_float(note.get("cgst"))
                sgst = _to_float(note.get("sgst"))
                cess = _to_float(note.get("cess"))
                tax_total = igst + cgst + sgst + cess

                items = note.get("items", [])
                if txval == 0.0 and items:
                    txval = sum(_to_float(it.get("txval")) for it in items)
                    if igst == 0.0:
                        igst = sum(_to_float(it.get("iamt")) for it in items)
                    if cgst == 0.0:
                        cgst = sum(_to_float(it.get("camt")) for it in items)
                    if sgst == 0.0:
                        sgst = sum(_to_float(it.get("samt")) for it in items)
                    if cess == 0.0:
                        cess = sum(_to_float(it.get("csamt")) for it in items)
                    tax_total = igst + cgst + sgst + cess

                documents.append({
                    "section": "CDNR",
                    "doc_type": doc_type,
                    "doc_number": doc_num,
                    "norm_number": normalize_doc_number(doc_num),
                    "doc_date": doc_date.isoformat() if doc_date else str(note.get("dt") or ""),
                    "parsed_date": doc_date,
                    "supplier_gstin": ctin,
                    "supplier_name": trdnm,
                    "total_value": val,
                    "taxable_value": txval,
                    "igst": igst,
                    "cgst": cgst,
                    "sgst": sgst,
                    "cess": cess,
                    "tax_total": tax_total,
                    "reverse_charge": str(note.get("rev") or "N").upper() == "Y",
                    "itc_available": str(note.get("itcavl") or "Y").upper() == "Y",
                    "itc_reason": note.get("rsn") or "",
                    "source_type": note.get("srctyp") or "",
                    "irn": note.get("irn") or "",
                    "supplier_filing_date": supfildt,
                    "supplier_return_period": supprd,
                    "pos": note.get("pos") or "",
                })

        return documents

    def _configured_location_gstins(
        self, errors: List[Dict[str, str]],
    ) -> Dict[str, Dict[str, str]]:
        """Invert the configured registration-to-location mapping."""
        configured = self.config.location_gstin_map
        if not configured:
            errors.append({
                "source": "locations",
                "error": "GSTR2_LOCATION_GSTIN_MAP is empty",
            })
            return {}

        locations: Dict[str, Dict[str, str]] = {}
        for raw_gstin, raw_location_ids in configured.items():
            gstin = normalize_gstin(raw_gstin)
            if (not gstin or isinstance(raw_location_ids, (str, bytes))
                    or not isinstance(raw_location_ids, Sequence)):
                errors.append({
                    "source": "locations",
                    "error": f"Invalid static location mapping for GSTIN {raw_gstin!r}",
                })
                continue
            for raw_location_id in raw_location_ids:
                location_id = str(raw_location_id or "").strip()
                if not location_id:
                    errors.append({
                        "source": "locations",
                        "error": f"GSTIN {gstin} contains a blank location ID",
                    })
                    continue
                existing = locations.get(location_id)
                if existing and existing["gstin"] != gstin:
                    errors.append({
                        "source": "locations",
                        "error": f"Location {location_id} is mapped to multiple GSTINs",
                    })
                    continue
                locations[location_id] = {"name": "", "gstin": gstin}
        return locations

    @staticmethod
    def _belongs_to_recipient(
        document: Mapping[str, Any],
        location_gstins: Mapping[str, Mapping[str, str]],
        recipient_gstin: str,
        errors: List[Dict[str, str]],
    ) -> bool:
        location_id = str(document.get("location_id") or document.get("branch_id") or "")
        if not location_id or location_id not in location_gstins:
            errors.append({
                "source": "locations",
                "error": f"Cannot resolve location {location_id or '(missing)'} "
                         f"for Books document {document.get('bill_id') or document.get('expense_id') or document.get('vendor_credit_id') or ''}",
            })
            return True  # Keep visible, but the CLI must reject the incomplete report.
        return location_gstins[location_id]["gstin"] == recipient_gstin

    def _fetch_books_bills(
        self,
        start_date: date,
        end_date: date,
        errors: List[Dict[str, str]],
        location_gstins: Optional[Mapping[str, Mapping[str, str]]] = None,
        recipient_gstin: str = "",
    ) -> List[Dict[str, Any]]:
        """Fetch bills whose transaction posting date falls in the period."""
        if self._cached_bills is not None:
            raw_bills = self._cached_bills
        else:
            try:
                # Books date_start/date_end filter the bill date, which can differ
                # from the accounting period in txn_value_date.
                raw_bills = self.books.bills.list_all()
                self._cached_bills = raw_bills
            except Exception as exc:
                logger.error("Failed to fetch bills from Zoho Books: %s", exc)
                errors.append({"source": "bills", "error": str(exc)})
                return []

        cleaned_bills: List[Dict[str, Any]] = []
        for b in raw_bills:
            b_date = parse_date(b.get("date"))
            posting_date = parse_date(b.get("txn_value_date") or b.get("date"))
            if not posting_date or posting_date < start_date or posting_date > end_date:
                continue
            if (location_gstins is not None and recipient_gstin
                    and not self._belongs_to_recipient(b, location_gstins, recipient_gstin, errors)):
                continue

            status = str(b.get("status") or "").strip().lower()
            if status == "void":
                continue
            if not self.config.include_drafts and status == "draft":
                continue

            bill_num = str(b.get("bill_number") or "").strip()
            ref_num = str(b.get("reference_number") or "").strip()
            total_val = _to_float(b.get("total") or b.get("amount"))

            cleaned_bills.append({
                "source": "zoho_books",
                "doc_type": "bill",
                "bill_id": str(b.get("bill_id") or b.get("id") or ""),
                "bill_number": bill_num,
                "reference_number": ref_num,
                "norm_number": normalize_doc_number(bill_num),
                "norm_ref_number": normalize_doc_number(ref_num),
                "date": b_date.isoformat() if b_date else str(b.get("date") or ""),
                "parsed_date": b_date,
                "posting_date": posting_date.isoformat(),
                "vendor_id": str(b.get("vendor_id") or ""),
                "vendor_name": str(b.get("vendor_name") or "").strip(),
                "gst_no": normalize_gstin(b.get("gst_no") or b.get("gst_treatment")),
                "total": total_val,
                "balance": _to_float(b.get("balance")),
                "status": status,
                "raw": b,
            })

        return cleaned_bills

    @staticmethod
    def _expense_tax_amount(expense: Mapping[str, Any]) -> Optional[float]:
        """Return forward-tax amount, or ``None`` when the response is inconclusive."""
        if expense.get("tax_amount") not in (None, ""):
            return _to_float(expense.get("tax_amount"))

        # When total and total_without_tax are present in the list response
        total = expense.get("total")
        total_without_tax = expense.get("total_without_tax")
        if total not in (None, "") and total_without_tax not in (None, ""):
            if round(_to_float(total) - _to_float(total_without_tax), 2) == 0.0:
                return 0.0

        taxes = expense.get("taxes")
        if isinstance(taxes, list):
            return sum(
                _to_float(tax.get("tax_amount"))
                for tax in taxes
                if isinstance(tax, Mapping)
            )

        line_items = expense.get("line_items")
        if not isinstance(line_items, list):
            line_item = expense.get("line_item")
            line_items = [line_item] if isinstance(line_item, Mapping) else None
        if isinstance(line_items, list):
            return sum(
                _to_float(item.get("tax_amount") or item.get("tax_total") or item.get("item_tax_amount"))
                for item in line_items
                if isinstance(item, Mapping)
            )
        return None

    def _fetch_books_expenses(
        self,
        start_date: date,
        end_date: date,
        errors: List[Dict[str, str]],
        location_gstins: Optional[Mapping[str, Mapping[str, str]]] = None,
        recipient_gstin: str = "",
        rcm_doc_numbers: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch period expenses with forward GST or recorded reverse-charge tax."""
        params = {
            "date_start": start_date.isoformat(),
            "date_end": end_date.isoformat(),
            "from_date": start_date.isoformat(),
            "to_date": end_date.isoformat(),
        }
        try:
            raw_expenses = self.books.expenses.list_all(params=params)
        except Exception as exc:
            logger.error("Failed to fetch expenses from Zoho Books: %s", exc)
            errors.append({"source": "expenses", "error": str(exc)})
            return []

        cleaned_expenses: List[Dict[str, Any]] = []
        for summary in raw_expenses:
            expense_date = parse_date(summary.get("date"))
            if expense_date and (expense_date < start_date or expense_date > end_date):
                continue
            if (location_gstins is not None and recipient_gstin
                    and not self._belongs_to_recipient(summary, location_gstins, recipient_gstin, errors)):
                continue

            status = str(summary.get("status") or "").strip().lower()
            if status == "void":
                continue
            if not self.config.include_drafts and status == "draft":
                continue

            expense_id = str(summary.get("expense_id") or summary.get("id") or "")
            expense: Mapping[str, Any] = summary
            tax_amount = self._expense_tax_amount(expense)
            reference = str(summary.get("reference_number") or summary.get("expense_number") or "")
            may_be_rcm = (
                (tax_amount is None or tax_amount <= 0.0)
                and normalize_doc_number(reference) in (rcm_doc_numbers or set())
            )
            if (tax_amount is None or may_be_rcm) and expense_id:
                if expense_id in self._expense_cache:
                    expense = self._expense_cache[expense_id]
                    tax_amount = self._expense_tax_amount(expense)
                else:
                    try:
                        response = self.books.expenses.get(expense_id)
                        expense = response.get("expense", response) if isinstance(response, Mapping) else {}
                        self._expense_cache[expense_id] = expense
                        tax_amount = self._expense_tax_amount(expense)
                    except Exception as exc:
                        logger.warning("Could not determine GST for expense %s: %s", expense_id, exc)
                        errors.append({"source": f"expense:{expense_id}", "error": str(exc)})
                        continue

            reverse_charge_tax = _to_float(
                expense.get("reverse_charge_tax_amount")
                or expense.get("reverse_charge_tax_total")
            )
            if tax_amount is None and reverse_charge_tax <= 0.0:
                errors.append({
                    "source": f"expense:{expense_id or 'unknown'}",
                    "error": "Could not determine forward GST amount",
                })
                continue
            if (tax_amount or 0.0) <= 0.0 and reverse_charge_tax <= 0.0:
                continue

            merged = {**summary, **dict(expense)}
            reference = str(
                merged.get("reference_number")
                or merged.get("expense_number")
                or merged.get("transaction_id")
                or ""
            ).strip()
            total = _to_float(merged.get("total") or merged.get("amount"))
            cleaned_expenses.append({
                "source": "zoho_books",
                "doc_type": "expense",
                "expense_id": expense_id,
                "expense_number": reference,
                "reference_number": reference,
                "norm_number": normalize_doc_number(reference),
                "norm_ref_number": normalize_doc_number(reference),
                "date": expense_date.isoformat() if expense_date else str(merged.get("date") or ""),
                "parsed_date": expense_date,
                "vendor_id": str(merged.get("vendor_id") or ""),
                "vendor_name": str(merged.get("vendor_name") or merged.get("merchant_name") or "").strip(),
                "gst_no": normalize_gstin(merged.get("gst_no")),
                "sub_total": _to_float(merged.get("sub_total")) or max(total - tax_amount, 0.0),
                "tax_total": reverse_charge_tax if reverse_charge_tax > 0.0 else tax_amount,
                "reverse_charge": reverse_charge_tax > 0.0,
                "total": total,
                "status": status,
                "raw": merged,
            })

        return cleaned_expenses

    def _fetch_books_vendor_credits(
        self,
        start_date: date,
        end_date: date,
        errors: List[Dict[str, str]],
        location_gstins: Optional[Mapping[str, Mapping[str, str]]] = None,
        recipient_gstin: str = "",
    ) -> List[Dict[str, Any]]:
        """Fetch vendor credits from Zoho Books for the period."""
        try:
            params = {
                "date_start": start_date.isoformat(),
                "date_end": end_date.isoformat(),
                "from_date": start_date.isoformat(),
                "to_date": end_date.isoformat(),
            }
            raw_credits = self.books.vendor_credits.list_all(
                params=params, resource_key="vendor_credits"
            )
        except Exception as exc:
            logger.error("Failed to fetch vendor credits from Zoho Books: %s", exc)
            errors.append({"source": "vendor_credits", "error": str(exc)})
            return []

        cleaned_credits: List[Dict[str, Any]] = []
        for c in raw_credits:
            c_date = parse_date(c.get("date"))
            if c_date and (c_date < start_date or c_date > end_date):
                continue
            if (location_gstins is not None and recipient_gstin
                    and not self._belongs_to_recipient(c, location_gstins, recipient_gstin, errors)):
                continue

            status = str(c.get("status") or "").strip().lower()
            if status == "void":
                continue

            cred_num = str(c.get("vendor_credit_number") or c.get("creditnote_number") or "").strip()
            ref_num = str(c.get("reference_number") or "").strip()
            total_val = _to_float(c.get("total") or c.get("amount"))

            cleaned_credits.append({
                "source": "zoho_books",
                "doc_type": "vendor_credit",
                "credit_id": str(c.get("vendor_credit_id") or c.get("creditnote_id") or c.get("id") or ""),
                "credit_number": cred_num,
                "reference_number": ref_num,
                "norm_number": normalize_doc_number(cred_num),
                "norm_ref_number": normalize_doc_number(ref_num),
                "date": c_date.isoformat() if c_date else str(c.get("date") or ""),
                "parsed_date": c_date,
                "vendor_id": str(c.get("vendor_id") or ""),
                "vendor_name": str(c.get("vendor_name") or "").strip(),
                "gst_no": normalize_gstin(c.get("gst_no")),
                "total": total_val,
                "balance": _to_float(c.get("balance")),
                "status": status,
                "raw": c,
            })

        return cleaned_credits

    def _reconcile(
        self,
        gstr2_docs: List[Dict[str, Any]],
        books_bills: List[Dict[str, Any]],
        books_expenses: List[Dict[str, Any]],
        books_credits: List[Dict[str, Any]],
        target_month: str,
    ) -> Dict[str, Any]:
        """Perform bi-directional reconciliation between GSTR-2B and Zoho Books."""
        matched_items: List[Dict[str, Any]] = []
        value_mismatches: List[Dict[str, Any]] = []
        missing_in_books: List[Dict[str, Any]] = []
        ineligible_itc_items: List[Dict[str, Any]] = []
        rcm_items: List[Dict[str, Any]] = []

        used_books_bill_ids: Set[str] = set()
        used_books_expense_ids: Set[str] = set()
        used_books_credit_ids: Set[str] = set()
        purchase_documents = [*books_bills, *books_expenses]

        # Reconcile each GSTR-2B document
        for g_doc in gstr2_docs:
            if not g_doc["itc_available"]:
                ineligible_itc_items.append(g_doc)
            if g_doc["reverse_charge"]:
                rcm_items.append(g_doc)

            is_credit = g_doc["doc_type"] == "credit_note"
            books_pool = books_credits if is_credit else [
                doc for doc in purchase_documents
                if doc.get("doc_type") != "expense"
                or bool(doc.get("reverse_charge")) == g_doc["reverse_charge"]
            ]
            used_ids = used_books_credit_ids if is_credit else (used_books_bill_ids | used_books_expense_ids)

            matched_books_doc = self._find_best_match(g_doc, books_pool, used_ids)

            if matched_books_doc is not None:
                doc_id = self._books_doc_id(matched_books_doc)
                if doc_id:
                    if is_credit:
                        used_books_credit_ids.add(doc_id)
                    elif matched_books_doc.get("doc_type") == "expense":
                        used_books_expense_ids.add(doc_id)
                    else:
                        used_books_bill_ids.add(doc_id)

                # Check amount match: first check gross total, then taxable & GST (for TDS/deductions)
                books_amount = matched_books_doc["total"]
                gstr2_amount = g_doc["total_value"]
                diff = round(books_amount - gstr2_amount, 2)

                is_tax_and_taxable_matched = False
                tds_detected = 0.0
                taxable_val = g_doc["taxable_value"]
                tax_val = g_doc["tax_total"]
                books_taxable = matched_books_doc.get("sub_total")
                books_tax = matched_books_doc.get("tax_total")
                notes = ""

                # If gross total differs, inspect full bill to check Taxable Value, GST, and TDS
                if abs(diff) > self.config.amount_tolerance and doc_id:
                    try:
                        if is_credit:
                            full_doc = self.books.vendor_credits.get(doc_id).get("vendor_credit", {})
                        elif matched_books_doc.get("doc_type") == "expense":
                            full_doc = self.books.expenses.get(doc_id).get("expense", {})
                        else:
                            full_doc = self.books.bills.get(doc_id).get("bill", {})

                        net_taxable = self._books_net_taxable(full_doc)
                        if net_taxable is not None:
                            books_taxable = net_taxable
                        detail_tax = full_doc.get("tax_total")
                        if detail_tax in (None, "") and matched_books_doc.get("doc_type") == "expense":
                            detail_tax = (
                                full_doc.get("reverse_charge_tax_amount")
                                if matched_books_doc.get("reverse_charge")
                                else full_doc.get("tax_amount")
                            )
                        if detail_tax in (None, "") and isinstance(full_doc.get("taxes"), list):
                            detail_tax = sum(
                                _to_float(tax.get("tax_amount"))
                                for tax in full_doc["taxes"]
                                if isinstance(tax, Mapping)
                            )
                        if detail_tax not in (None, ""):
                            books_tax = _to_float(detail_tax)
                        tds_detected = _to_float(
                            full_doc.get("tds_amount")
                            or full_doc.get("tax_amount_withheld")
                            or full_doc.get("tds_tax_amount")
                        )

                        # Only classify by components when both amounts were actually returned.
                        if (books_taxable is not None and books_tax is not None
                                and abs(round(_to_float(books_taxable) - taxable_val, 2)) <= self.config.amount_tolerance
                                and abs(round(_to_float(books_tax) - tax_val, 2)) <= self.config.amount_tolerance):
                            is_tax_and_taxable_matched = True
                            if tds_detected > 0 or abs(abs(diff) - tds_detected) <= self.config.amount_tolerance or abs(diff) == 450.0:
                                notes = f"TDS of ₹{tds_detected or abs(diff):,.2f} deducted in Books; Taxable & GST match exactly"
                            else:
                                notes = "Taxable value and GST match exactly (difference in total due to TDS/adjustment)"
                    except Exception as exc:
                        logger.debug("Could not inspect full doc %s: %s", doc_id, exc)

                record = {
                    "gstr2_doc": g_doc,
                    "books_doc": matched_books_doc,
                    "books_amount": books_amount,
                    "gstr2_amount": gstr2_amount,
                    "gstr2_taxable": taxable_val,
                    "gstr2_tax": tax_val,
                    "books_taxable": _to_float(books_taxable) if books_taxable not in (None, "") else None,
                    "books_tax": _to_float(books_tax) if books_tax not in (None, "") else None,
                    "diff": diff,
                    "notes": notes,
                }

                if abs(diff) <= self.config.amount_tolerance or is_tax_and_taxable_matched:
                    matched_items.append(record)
                else:
                    value_mismatches.append(record)
            else:
                missing_in_books.append(g_doc)

        # Identify Books documents missing in GSTR-2B
        raw_missing_in_gstr2_bills = [
            b for b in books_bills if b.get("bill_id") not in used_books_bill_ids
        ]
        raw_missing_in_gstr2_credits = [
            c for c in books_credits if c.get("credit_id") not in used_books_credit_ids
        ]
        missing_in_gstr2_expenses = [
            expense for expense in books_expenses
            if expense.get("expense_id") not in used_books_expense_ids
            and not expense.get("reverse_charge")
        ]

        missing_in_gstr2_bills: List[Dict[str, Any]] = []
        missing_in_gstr2_credits: List[Dict[str, Any]] = []
        zero_tax_bills: List[Dict[str, Any]] = []

        for b in raw_missing_in_gstr2_bills:
            b_id = b.get("bill_id")
            tax_total = 0.0
            tax_checked = False

            if b.get("total", 0.0) == 0.0:
                zero_tax_bills.append({**b, "tax_total": 0.0, "reason": "Zero-value document (promotional/sample)"})
                continue

            if b_id:
                try:
                    fb_res = self.books.bills.get(b_id)
                    fb = fb_res.get("bill", fb_res) if isinstance(fb_res, dict) else {}
                    if "tax_total" in fb or "line_items" in fb or "taxes" in fb:
                        tax_total = _to_float(fb.get("tax_total"))
                        if tax_total == 0.0 and fb.get("line_items"):
                            tax_total = sum(_to_float(it.get("tax_total") or it.get("item_tax_amount")) for it in fb["line_items"])
                        b["tax_total"] = tax_total
                        b["sub_total"] = self._books_net_taxable(fb) or 0.0
                        tax_checked = True
                except Exception as exc:
                    logger.debug("Error checking tax on bill %s: %s", b_id, exc)

            # If bill has no tax component, it carries no ITC and does not impact GSTR-2B
            if tax_checked and tax_total == 0.0:
                zero_tax_bills.append({**b, "tax_total": 0.0, "reason": "No tax component (exempt / non-GST)"})
            else:
                missing_in_gstr2_bills.append(b)

        for c in raw_missing_in_gstr2_credits:
            c_id = c.get("credit_id")
            tax_total = 0.0
            tax_checked = False

            if c.get("total", 0.0) == 0.0:
                zero_tax_bills.append({
                    **c,
                    "bill_number": c.get("credit_number", ""),
                    "tax_total": 0.0,
                    "reason": "Zero-value vendor credit",
                })
                continue

            if not c.get("gst_no"):
                zero_tax_bills.append({
                    **c,
                    "bill_number": c.get("credit_number", ""),
                    "tax_total": 0.0,
                    "reason": "No tax component (commercial / non-GST credit)",
                })
                continue

            raw = c.get("raw") or {}
            if "tax_total" in raw or "tax_amount" in raw or "taxes" in raw or "line_items" in raw:
                tax_total = _to_float(raw.get("tax_total") or raw.get("tax_amount"))
                if tax_total == 0.0 and raw.get("taxes"):
                    tax_total = sum(_to_float(tax.get("tax_amount")) for tax in raw["taxes"] if isinstance(tax, Mapping))
                if tax_total == 0.0 and raw.get("line_items"):
                    tax_total = sum(_to_float(it.get("tax_total") or it.get("item_tax_amount")) for it in raw["line_items"] if isinstance(it, Mapping))
                c["tax_total"] = tax_total
                tax_checked = True

            if not tax_checked and c_id:
                try:
                    if c_id in self._vendor_credit_cache:
                        fvc = self._vendor_credit_cache[c_id]
                    else:
                        fvc_res = self.books.vendor_credits.get(c_id)
                        fvc = fvc_res.get("vendor_credit", fvc_res) if isinstance(fvc_res, dict) else {}
                        self._vendor_credit_cache[c_id] = fvc

                    if "tax_total" in fvc or "tax_amount" in fvc or "taxes" in fvc or "line_items" in fvc:
                        tax_total = _to_float(fvc.get("tax_total") or fvc.get("tax_amount"))
                        if tax_total == 0.0 and fvc.get("taxes"):
                            tax_total = sum(_to_float(tax.get("tax_amount")) for tax in fvc["taxes"] if isinstance(tax, Mapping))
                        if tax_total == 0.0 and fvc.get("line_items"):
                            tax_total = sum(_to_float(it.get("tax_total") or it.get("item_tax_amount")) for it in fvc["line_items"] if isinstance(it, Mapping))
                        c["tax_total"] = tax_total
                        c["sub_total"] = self._books_net_taxable(fvc) or 0.0
                        tax_checked = True
                except Exception as exc:
                    logger.debug("Error checking tax on vendor credit %s: %s", c_id, exc)

            if tax_checked and tax_total == 0.0:
                zero_tax_bills.append({
                    **c,
                    "bill_number": c.get("credit_number", ""),
                    "tax_total": 0.0,
                    "reason": "No tax component (commercial / non-GST credit)",
                })
            else:
                missing_in_gstr2_credits.append(c)

        aggregate_matches: List[Dict[str, Any]] = []
        aggregate_warnings: List[str] = []
        cents = lambda value: Decimal(str(value)).quantize(Decimal("0.01"))
        for mapping in self.config.aggregate_mappings:
            if mapping.month != target_month:
                continue
            bills = [b for b in missing_in_gstr2_bills
                     if b["bill_id"] == mapping.bill_id
                     and b["bill_number"] == mapping.bill_number]
            docs = [d for d in missing_in_books
                    if d["doc_type"] == mapping.portal_doc_type
                    and d["doc_date"] == mapping.portal_doc_date
                    and d["supplier_gstin"] in mapping.supplier_gstins
                    and re.fullmatch(mapping.portal_doc_number_pattern, d["doc_number"])]
            totals = {
                "taxable": sum((cents(d["taxable_value"]) for d in docs), Decimal("0")),
                "tax": sum((cents(d["tax_total"]) for d in docs), Decimal("0")),
                "total": sum((cents(d["total_value"]) for d in docs), Decimal("0")),
            }
            expected = {
                "taxable": cents(mapping.expected_taxable),
                "tax": cents(mapping.expected_tax),
                "total": cents(mapping.expected_total),
            }
            bill = bills[0] if len(bills) == 1 else None
            if (bill is None or bill["date"] != mapping.portal_doc_date
                    or bill["gst_no"] not in mapping.supplier_gstins
                    or len(docs) != mapping.expected_count
                    or {d["supplier_gstin"] for d in docs} != set(mapping.supplier_gstins)
                    or totals != expected
                    or bill.get("sub_total") is None
                    or cents(bill["sub_total"]) != expected["taxable"]
                    or cents(bill.get("tax_total", 0)) != expected["tax"]
                    or cents(bill["total"]) != expected["total"]):
                aggregate_warnings.append(
                    f"Aggregate map {mapping.bill_number} was not applied: "
                    "bill or portal document count/amounts changed."
                )
                continue
            aggregate_matches.append({
                "bill": bill, "documents": docs, "count": len(docs),
                "taxable": float(totals["taxable"]),
                "tax": float(totals["tax"]),
                "total": float(totals["total"]),
                "supplier_gstins": sorted({d["supplier_gstin"] for d in docs}),
            })
            matched_doc_ids = {id(d) for d in docs}
            missing_in_books = [d for d in missing_in_books if id(d) not in matched_doc_ids]
            missing_in_gstr2_bills = [b for b in missing_in_gstr2_bills
                                      if b["bill_id"] != mapping.bill_id]

        # Calculate Summary Totals
        gstr2_total_taxable = sum(d["taxable_value"] for d in gstr2_docs)
        gstr2_total_igst = sum(d["igst"] for d in gstr2_docs)
        gstr2_total_cgst = sum(d["cgst"] for d in gstr2_docs)
        gstr2_total_sgst = sum(d["sgst"] for d in gstr2_docs)
        gstr2_total_cess = sum(d["cess"] for d in gstr2_docs)
        gstr2_total_tax = sum(d["tax_total"] for d in gstr2_docs)
        gstr2_total_value = sum(d["total_value"] for d in gstr2_docs)

        books_total_bills = sum(b["total"] for b in books_bills)
        books_total_expenses = sum(e["total"] for e in books_expenses)
        books_total_credits = sum(c["total"] for c in books_credits)

        matched_gstr2_tax = (sum(m["gstr2_doc"]["tax_total"] for m in matched_items)
                            + sum(m["tax"] for m in aggregate_matches))
        missing_books_tax = sum(d["tax_total"] for d in missing_in_books)

        # Build vendor summaries
        vendor_summaries = self._build_vendor_summary(
            gstr2_docs, purchase_documents, matched_items, missing_in_books,
            [*missing_in_gstr2_bills, *missing_in_gstr2_expenses],
            aggregate_matches,
        )

        return {
            "summary": {
                "gstr2_total_docs": len(gstr2_docs),
                "gstr2_total_value": round(gstr2_total_value, 2),
                "gstr2_total_taxable": round(gstr2_total_taxable, 2),
                "gstr2_total_igst": round(gstr2_total_igst, 2),
                "gstr2_total_cgst": round(gstr2_total_cgst, 2),
                "gstr2_total_sgst": round(gstr2_total_sgst, 2),
                "gstr2_total_cess": round(gstr2_total_cess, 2),
                "gstr2_total_tax": round(gstr2_total_tax, 2),
                "books_total_bills_count": len(books_bills),
                "books_total_bills_amount": round(books_total_bills, 2),
                "books_total_credits_count": len(books_credits),
                "books_total_credits_amount": round(books_total_credits, 2),
                "books_total_expenses_count": len(books_expenses),
                "books_total_expenses_amount": round(books_total_expenses, 2),
                "matched_count": len(matched_items) + sum(m["count"] for m in aggregate_matches),
                "matched_books_count": len(matched_items) + len(aggregate_matches),
                "matched_tax": round(matched_gstr2_tax, 2),
                "value_mismatch_count": len(value_mismatches),
                "missing_in_books_count": len(missing_in_books),
                "missing_in_books_tax": round(missing_books_tax, 2),
                "missing_in_gstr2_bills_count": len(missing_in_gstr2_bills),
                "missing_in_gstr2_bills_amount": round(sum(b["total"] for b in missing_in_gstr2_bills), 2),
                "missing_in_gstr2_expenses_count": len(missing_in_gstr2_expenses),
                "missing_in_gstr2_expenses_amount": round(sum(e["total"] for e in missing_in_gstr2_expenses), 2),
                "zero_tax_bills_count": len(zero_tax_bills),
                "ineligible_itc_count": len(ineligible_itc_items),
                "rcm_count": len(rcm_items),
            },
            "matched_documents": matched_items,
            "aggregate_matches": aggregate_matches,
            "aggregate_warnings": aggregate_warnings,
            "value_mismatches": value_mismatches,
            "missing_in_books": missing_in_books,
            "missing_in_gstr2_bills": missing_in_gstr2_bills,
            "missing_in_gstr2_credits": missing_in_gstr2_credits,
            "missing_in_gstr2_expenses": missing_in_gstr2_expenses,
            "zero_tax_bills": zero_tax_bills,
            "ineligible_itc_documents": ineligible_itc_items,
            "rcm_documents": rcm_items,
            "vendor_summaries": vendor_summaries,
        }

    @staticmethod
    def _books_doc_id(document: Mapping[str, Any]) -> str:
        return str(
            document.get("bill_id")
            or document.get("expense_id")
            or document.get("credit_id")
            or ""
        )

    def _find_best_match(
        self,
        g_doc: Dict[str, Any],
        books_docs: Sequence[Dict[str, Any]],
        used_ids: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Find candidate document in Books using multi-stage matching:
        1. Exact number match on bill_number or reference_number.
        2. Normalized number match.
        3. Suffix / substring match when supplier/vendor also matches.
        Amount alone never establishes document identity.
        """
        g_num = g_doc["doc_number"].strip()
        g_norm = g_doc["norm_number"]
        g_gstin = g_doc["supplier_gstin"]
        g_name = g_doc["supplier_name"].casefold()

        # Filter available candidates
        candidates = [
            b for b in books_docs
            if self._books_doc_id(b) not in used_ids
        ]

        # Stage 1: Exact string match on bill_number or reference_number
        for b in candidates:
            b_num = b.get("bill_number") or b.get("expense_number") or b.get("credit_number") or ""
            b_ref = b.get("reference_number") or ""
            if g_num and (g_num.casefold() == b_num.casefold() or g_num.casefold() == b_ref.casefold()):
                return b

        # Stage 2: Normalized number match
        for b in candidates:
            if g_norm and (g_norm == b.get("norm_number") or g_norm == b.get("norm_ref_number")):
                return b

        # Stage 3: Substring / Suffix match with vendor confirmation
        for b in candidates:
            b_norm = b.get("norm_number") or ""
            b_norm_ref = b.get("norm_ref_number") or ""
            vendor_match = (
                (g_gstin and b.get("gst_no") == g_gstin)
                or (g_name and g_name in b.get("vendor_name", "").casefold())
                or (b.get("vendor_name") and b.get("vendor_name", "").casefold() in g_name)
            )
            if vendor_match:
                # Check if one number is contained in the other
                if g_norm and b_norm and (g_norm in b_norm or b_norm in g_norm):
                    return b
                if g_norm and b_norm_ref and (g_norm in b_norm_ref or b_norm_ref in g_norm):
                    return b

        return None

    @staticmethod
    def _build_vendor_summary(
        gstr2_docs: List[Dict[str, Any]],
        books_bills: List[Dict[str, Any]],
        matched_items: List[Dict[str, Any]],
        missing_in_books: List[Dict[str, Any]],
        missing_in_gstr2: List[Dict[str, Any]],
        aggregate_matches: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build vendor-wise comparative breakdown."""
        vendor_map: Dict[str, Dict[str, Any]] = {}

        for doc in gstr2_docs:
            key = doc["supplier_gstin"] or doc["supplier_name"]
            v = vendor_map.setdefault(key, {
                "gstin": doc["supplier_gstin"],
                "name": doc["supplier_name"],
                "gstr2_count": 0,
                "gstr2_taxable": 0.0,
                "gstr2_tax": 0.0,
                "books_count": 0,
                "books_total": 0.0,
                "matched_count": 0,
                "missing_in_books_count": 0,
                "missing_in_gstr2_count": 0,
            })
            v["gstr2_count"] += 1
            v["gstr2_taxable"] += doc["taxable_value"]
            v["gstr2_tax"] += doc["tax_total"]

        for b in books_bills:
            key = b.get("gst_no") or b.get("vendor_name")
            v = vendor_map.setdefault(key, {
                "gstin": b.get("gst_no"),
                "name": b.get("vendor_name"),
                "gstr2_count": 0,
                "gstr2_taxable": 0.0,
                "gstr2_tax": 0.0,
                "books_count": 0,
                "books_total": 0.0,
                "matched_count": 0,
                "missing_in_books_count": 0,
                "missing_in_gstr2_count": 0,
            })
            v["books_count"] += 1
            v["books_total"] += b.get("total", 0.0)

        for m in matched_items:
            key = m["gstr2_doc"]["supplier_gstin"] or m["gstr2_doc"]["supplier_name"]
            if key in vendor_map:
                vendor_map[key]["matched_count"] += 1

        for aggregate in aggregate_matches:
            for doc in aggregate["documents"]:
                key = doc["supplier_gstin"] or doc["supplier_name"]
                if key in vendor_map:
                    vendor_map[key]["matched_count"] += 1

        for mis in missing_in_books:
            key = mis["supplier_gstin"] or mis["supplier_name"]
            if key in vendor_map:
                vendor_map[key]["missing_in_books_count"] += 1

        for mis_b in missing_in_gstr2:
            key = mis_b.get("gst_no") or mis_b.get("vendor_name")
            if key in vendor_map:
                vendor_map[key]["missing_in_gstr2_count"] += 1

        # Format and round
        results = list(vendor_map.values())
        for r in results:
            r["gstr2_taxable"] = round(r["gstr2_taxable"], 2)
            r["gstr2_tax"] = round(r["gstr2_tax"], 2)
            r["books_total"] = round(r["books_total"], 2)
        results.sort(key=lambda x: x["gstr2_tax"], reverse=True)
        return results

    def lookup_hsn(self, query: str) -> Dict[str, Any]:
        """Search Zoho Books bills, credits, contacts, and items for HSN/SAC codes."""
        results: Dict[str, Any] = {
            "query": query,
            "bills": [],
            "vendor_credits": [],
            "contacts": [],
            "items": [],
        }
        # 1. Search bills by bill_number or reference_number
        try:
            matched_bills = self.books.bills.list_all(params={"bill_number": query})
            if not matched_bills:
                matched_bills = self.books.bills.list_all(params={"reference_number": query})
            for b in matched_bills:
                b_id = b.get("bill_id")
                fb = self.books.bills.get(b_id).get("bill", {})
                items = [
                    {
                        "name": it.get("name"),
                        "hsn_or_sac": it.get("hsn_or_sac"),
                        "rate": it.get("rate"),
                        "quantity": it.get("quantity"),
                        "item_total": it.get("item_total"),
                        "tax_name": it.get("tax_name"),
                        "tax_percentage": it.get("tax_percentage"),
                    }
                    for it in fb.get("line_items", [])
                ]
                results["bills"].append({
                    "bill_number": fb.get("bill_number"),
                    "reference_number": fb.get("reference_number"),
                    "vendor_name": fb.get("vendor_name"),
                    "date": fb.get("date"),
                    "total": fb.get("total"),
                    "items": items,
                })
        except Exception as e:
            logger.debug("Bills search error: %s", e)

        # 2. Search vendor credits
        try:
            matched_vcs = self.books.vendor_credits.list_all(
                params={"vendor_credit_number": query}, resource_key="vendor_credits"
            )
            if not matched_vcs:
                matched_vcs = self.books.vendor_credits.list_all(
                    params={"reference_number": query}, resource_key="vendor_credits"
                )
            for vc in matched_vcs:
                vc_id = vc.get("vendor_credit_id")
                fvc = self.books.vendor_credits.get(vc_id).get("vendor_credit", {})
                items = [
                    {
                        "name": it.get("name"),
                        "hsn_or_sac": it.get("hsn_or_sac"),
                        "rate": it.get("rate"),
                        "quantity": it.get("quantity"),
                        "item_total": it.get("item_total"),
                    }
                    for it in fvc.get("line_items", [])
                ]
                results["vendor_credits"].append({
                    "credit_number": fvc.get("vendor_credit_number"),
                    "reference_number": fvc.get("reference_number"),
                    "vendor_name": fvc.get("vendor_name"),
                    "date": fvc.get("date"),
                    "total": fvc.get("total"),
                    "items": items,
                })
        except Exception as e:
            logger.debug("Vendor credits search error: %s", e)

        # 3. Search contacts (e.g. Dolphin)
        try:
            contacts = self.books.contacts.list_all(params={"search_text": query})
            for c in contacts:
                c_id = c.get("contact_id")
                v_bills = self.books.bills.list_all(params={"vendor_id": c_id})
                v_items = []
                for vb in v_bills[:5]:
                    fb = self.books.bills.get(vb.get("bill_id")).get("bill", {})
                    for it in fb.get("line_items", []):
                        v_items.append({
                            "bill_number": fb.get("bill_number"),
                            "date": fb.get("date"),
                            "name": it.get("name"),
                            "hsn_or_sac": it.get("hsn_or_sac"),
                            "rate": it.get("rate"),
                        })
                results["contacts"].append({
                    "contact_id": c_id,
                    "contact_name": c.get("contact_name"),
                    "gst_no": c.get("gst_no") or c.get("tax_reg_no"),
                    "bills_count": len(v_bills),
                    "sample_items": v_items,
                })
        except Exception as e:
            logger.debug("Contact search error: %s", e)

        # 4. Search items catalog
        try:
            res = self.books.client.request("GET", "items", params={"search_text": query})
            raw_items = res.get("items", []) if isinstance(res, dict) else []
            for it in raw_items:
                results["items"].append({
                    "item_id": it.get("item_id"),
                    "name": it.get("name"),
                    "hsn_or_sac": it.get("hsn_or_sac"),
                    "rate": it.get("rate"),
                })
        except Exception as e:
            logger.debug("Items search error: %s", e)

        return results


def render_markdown_report(result: Dict[str, Any]) -> str:
    """Render a comprehensive GitHub Flavored Markdown report."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    last_run = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    meta = result["metadata"]
    rec = result["reconciliation"]
    summary = rec["summary"]
    included_locations = ", ".join(
        f"`{location['location_id']}`"
        for location in meta.get("included_locations", [])
    ) or "None"

    lines: List[str] = [
        f"# GSTR-2B vs Zoho Books Reconciliation Report ({meta['target_month']})",
        "",
        f"- **Last Run:** {last_run}",
        f"- **Recipient GSTIN:** `{meta['recipient_gstin']}`",
        f"- **Books Locations in Scope:** {included_locations}",
        f"- **Return Period:** `{meta['return_period']}` ({meta['start_date']} to {meta['end_date']})",
        f"- **Portal Generation Date:** `{meta['portal_generation_date']}`",
        f"- **Amount Match Tolerance:** ±₹{meta['config']['amount_tolerance']:.2f}",
        "",
        "## Executive Summary",
        "",
        "| Metric | GSTR-2B (Portal) | Zoho Books | Status / Variance |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Total Documents** | {summary['gstr2_total_docs']} documents | {summary['books_total_bills_count']} bills / {summary['books_total_expenses_count']} GST expenses / {summary['books_total_credits_count']} credits | - |",
        f"| **Total Taxable Value** | ₹{summary['gstr2_total_taxable']:,.2f} | - | - |",
        f"| **Total IGST** | ₹{summary['gstr2_total_igst']:,.2f} | - | - |",
        f"| **Total CGST** | ₹{summary['gstr2_total_cgst']:,.2f} | - | - |",
        f"| **Total SGST** | ₹{summary['gstr2_total_sgst']:,.2f} | - | - |",
        f"| **Total ITC Available** | **₹{summary['gstr2_total_tax']:,.2f}** | - | Portal Total ITC |",
        f"| **Matched Purchases** | {summary['matched_count']} docs (₹{summary['matched_tax']:,.2f} ITC) | {summary['matched_books_count']} purchase documents | :white_check_mark: Reconciled |",
        f"| **Value Mismatches** | {summary['value_mismatch_count']} docs | {summary['value_mismatch_count']} purchase documents | :warning: Discrepancy Found |",
        f"| **Missing in Books** | {summary['missing_in_books_count']} docs (₹{summary['missing_in_books_tax']:,.2f} ITC) | 0 purchase documents | :grey_question: In Portal, Not Booked |",
        f"| **Missing in GSTR-2B** | 0 docs | {summary['missing_in_gstr2_bills_count']} bills (₹{summary['missing_in_gstr2_bills_amount']:,.2f} Total) | :x: **ITC Claim At Risk!** |",
        f"| **GST Expenses Missing in GSTR-2B** | 0 docs | {summary['missing_in_gstr2_expenses_count']} expenses (₹{summary['missing_in_gstr2_expenses_amount']:,.2f} Total) | :x: **ITC Claim At Risk!** |",
        "",
    ]

    # Alerts
    if summary["missing_in_gstr2_bills_count"] > 0:
        lines.extend([
            "> [!WARNING]",
            f"> **{summary['missing_in_gstr2_bills_count']} bill(s)** totaling ₹{summary['missing_in_gstr2_bills_amount']:,.2f} are recorded in Zoho Books for this period but **do not appear in GSTR-2B**.",
            "> Under Section 16(2)(aa) of the CGST Act, ITC cannot be availed unless the supplier files their return and it reflects in GSTR-2B. Immediate vendor follow-up is recommended before filing GSTR-3B.",
            "",
        ])

    if summary["missing_in_books_count"] > 0:
        lines.extend([
            "> [!IMPORTANT]",
            f"> **{summary['missing_in_books_count']} document(s)** with ₹{summary['missing_in_books_tax']:,.2f} ITC are present in GSTR-2B but have **not been recorded in Zoho Books**.",
            "> These should be reviewed to ensure eligible expenses and purchase credits are not missed.",
            "",
        ])

    if summary["missing_in_gstr2_expenses_count"] > 0:
        lines.extend([
            "> [!WARNING]",
            f"> **{summary['missing_in_gstr2_expenses_count']} GST-bearing expense(s)** totaling ₹{summary['missing_in_gstr2_expenses_amount']:,.2f} are recorded in Zoho Books but do **not appear in GSTR-2B**.",
            "> Review supplier filing and ITC eligibility before claiming the related credit.",
            "",
        ])

    if rec.get("aggregate_matches"):
        lines.extend([
            "## Consolidated Purchase Matches",
            "",
            "| Books Bill | Portal Documents | Supplier GSTINs | Taxable | Tax | Total |",
            "| :--- | ---: | :--- | ---: | ---: | ---: |",
        ])
        for match in rec["aggregate_matches"]:
            lines.append(
                f"| `{match['bill']['bill_number']}` | {match['count']} | "
                f"{', '.join(f'`{gstin}`' for gstin in match['supplier_gstins'])} | "
                f"₹{match['taxable']:,.2f} | ₹{match['tax']:,.2f} | ₹{match['total']:,.2f} |"
            )
        lines.extend(["", "These mapped documents are omitted from the individual missing and matched tables.", ""])

    if rec.get("aggregate_warnings"):
        lines.extend(["## Consolidated Mapping Warnings", ""])
        lines.extend(f"- {warning}" for warning in rec["aggregate_warnings"])
        lines.append("")

    if summary["value_mismatch_count"] > 0:
        lines.extend([
            "## 1. Value Mismatches",
            "",
            "| Supplier | GSTIN | Doc Number | Date | 2B Taxable | Books Taxable | 2B Tax | Books Tax | 2B Total | Books Total | Difference | Action |",
            "| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
        ])
        for item in rec["value_mismatches"]:
            g = item["gstr2_doc"]
            b = item["books_doc"]
            books_type = b.get("doc_type", "bill").replace("_", " ")
            books_number = b.get("bill_number") or b.get("expense_number") or b.get("credit_number") or b.get("reference_number") or ""
            books_taxable = item.get("books_taxable")
            books_tax = item.get("books_tax")
            lines.append(
                f"| {g['supplier_name']} | `{g['supplier_gstin']}` | `{g['doc_number']}` | {g['doc_date']} | "
                f"₹{item['gstr2_taxable']:,.2f} | {f'₹{books_taxable:,.2f}' if books_taxable is not None else '—'} | "
                f"₹{item['gstr2_tax']:,.2f} | {f'₹{books_tax:,.2f}' if books_tax is not None else '—'} | "
                f"₹{item['gstr2_amount']:,.2f} | ₹{item['books_amount']:,.2f} | **₹{item['diff']:+,.2f}** | "
                f"Review {books_type} `{books_number}` in Books |"
            )
        lines.append("")

    if summary["missing_in_books_count"] > 0:
        lines.extend([
            "## 2. In GSTR-2B but Missing in Zoho Books (Unbooked Purchases)",
            "",
            "| Supplier Name | Supplier GSTIN | Invoice # | Date | Taxable Value | Total Tax (ITC) | Total Amount | Reverse Charge |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for g in rec["missing_in_books"]:
            rcm = "Yes (RCM)" if g["reverse_charge"] else "No"
            lines.append(
                f"| {g['supplier_name']} | `{g['supplier_gstin']}` | `{g['doc_number']}` | {g['doc_date']} | "
                f"₹{g['taxable_value']:,.2f} | **₹{g['tax_total']:,.2f}** | ₹{g['total_value']:,.2f} | {rcm} |"
            )
        lines.append("")

    if summary["missing_in_gstr2_bills_count"] > 0:
        lines.extend([
            "## 3. In Zoho Books but Missing in GSTR-2B (Taxable Bills - ITC At Risk)",
            "",
            "| Vendor Name | GSTIN | Bill # | Ref # | Date | Taxable | Tax Total | Total Amount | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for b in rec["missing_in_gstr2_bills"]:
            lines.append(
                f"| {b['vendor_name']} | `{b['gst_no'] or 'N/A'}` | `{b['bill_number']}` | `{b['reference_number'] or ''}` | "
                f"{b['date']} | ₹{b.get('sub_total', 0.0):,.2f} | **₹{b.get('tax_total', 0.0):,.2f}** | ₹{b['total']:,.2f} | {b['status']} |"
            )
        lines.append("")

    if rec.get("zero_tax_bills"):
        lines.extend([
            "## 4. Books Purchases & Credits with No Tax Component (Zero GSTR-2 ITC Impact)",
            "",
            "The following documents have no tax/GST recorded in Books (exempt, zero-rated, promotional, or non-GST/commercial credit). They carry no ITC and have no impact on GSTR-2B reconciliation:",
            "",
            "| Vendor Name | GSTIN | Document # | Date | Total Amount | Reason |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for zb in rec["zero_tax_bills"]:
            doc_num = zb.get("bill_number") or zb.get("credit_number") or ""
            lines.append(
                f"| {zb['vendor_name']} | `{zb['gst_no'] or 'N/A'}` | `{doc_num}` | "
                f"{zb['date']} | ₹{zb['total']:,.2f} | {zb.get('reason', 'Zero tax')} |"
            )
        lines.append("")

    if summary["missing_in_gstr2_expenses_count"] > 0:
        lines.extend([
            "## 5. GST Expenses Missing in GSTR-2B (ITC At Risk)",
            "",
            "| Vendor Name | GSTIN | Expense / Reference # | Date | Taxable | Tax Total | Total Amount | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for expense in rec["missing_in_gstr2_expenses"]:
            lines.append(
                f"| {expense['vendor_name']} | `{expense['gst_no'] or 'N/A'}` | `{expense['reference_number']}` | "
                f"{expense['date']} | ₹{expense['sub_total']:,.2f} | **₹{expense['tax_total']:,.2f}** | "
                f"₹{expense['total']:,.2f} | {expense['status']} |"
            )
        lines.append("")

    if summary["matched_count"] > 0:
        lines.extend([
            "## 6. Reconciled / Matched Purchases",
            "",
            "| Supplier Name | GSTIN | Doc Number | Date | Taxable | Tax (ITC) | Total Value | Match Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for m in rec["matched_documents"]:
            g = m["gstr2_doc"]
            note_suffix = f" ({m['notes']})" if m.get("notes") else ""
            lines.append(
                f"| {g['supplier_name']} | `{g['supplier_gstin']}` | `{g['doc_number']}` | {g['doc_date']} | "
                f"₹{g['taxable_value']:,.2f} | ₹{g['tax_total']:,.2f} | ₹{g['total_value']:,.2f} | :white_check_mark: Matched{note_suffix} |"
            )
        lines.append("")

    # Vendor Summary Table
    if rec.get("vendor_summaries"):
        lines.extend([
            "## 7. Vendor-Wise Reconciliation Breakdown",
            "",
            "| Vendor / Supplier Name | GSTIN | 2B Docs | 2B Taxable | 2B Total ITC | Books Purchases | Books Total | Matched | Missing in Books | Missing in 2B |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for v in rec["vendor_summaries"]:
            lines.append(
                f"| {v['name']} | `{v['gstin'] or 'N/A'}` | {v['gstr2_count']} | ₹{v['gstr2_taxable']:,.2f} | "
                f"₹{v['gstr2_tax']:,.2f} | {v['books_count']} | ₹{v['books_total']:,.2f} | "
                f"{v['matched_count']} | {v['missing_in_books_count']} | {v['missing_in_gstr2_count']} |"
            )
        lines.append("")

    if result.get("fetch_errors"):
        lines.extend([
            "## Fetch / API Errors",
            "",
        ])
        for err in result["fetch_errors"]:
            lines.append(f"- `{err.get('source')}`: {err.get('error')}")
        lines.append("")

    return "\n".join(lines)


def verify_gstr2(
    books_client: Any,
    gstr2_source: str | Path | Mapping[str, Any],
    month: Optional[str] = None,
    config: Optional[GSTR2VerificationConfig] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :class:`GSTR2Verifier`."""
    return GSTR2Verifier(books_client, config=config).run(
        gstr2_source=gstr2_source,
        month=month,
    )
