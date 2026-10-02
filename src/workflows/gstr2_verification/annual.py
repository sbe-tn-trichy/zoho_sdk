"""Resolve timing differences between completed monthly GSTR-2B runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .verifier import normalize_doc_number


def fiscal_months(start_year: int) -> tuple[str, ...]:
    return tuple(f"{start_year + (month < 4)}-{month:02d}"
                 for month in (*range(4, 13), *range(1, 4)))


def reconcile_fiscal_year(results: Sequence[dict[str, Any]], *, tolerance: float) -> list[dict[str, Any]]:
    """Remove unique, amount-consistent cross-month gaps and return an audit trail.

    Results are mutated only after all candidate pairs have been checked. Ambiguous
    identities and value differences remain visible for manual review.
    """
    portal: dict[tuple[str, str, str, bool], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    books: dict[tuple[str, str, str, bool], list[tuple[dict[str, Any], dict[str, Any], str]]] = defaultdict(list)
    for result in results:
        rec = result["reconciliation"]
        for doc in rec["missing_in_books"]:
            number = doc.get("norm_number") or normalize_doc_number(doc.get("doc_number"))
            gstin = str(doc.get("supplier_gstin") or "").upper()
            if gstin and number:
                kind = "credit" if doc.get("doc_type") == "credit_note" else "purchase"
                portal[(gstin, number, kind, bool(doc.get("reverse_charge")))].append((result, doc))
        for category, kind in (("missing_in_gstr2_bills", "purchase"),
                               ("missing_in_gstr2_expenses", "purchase"),
                               ("missing_in_gstr2_credits", "credit")):
            for doc in rec[category]:
                gstin = str(doc.get("gst_no") or "").upper()
                numbers = {normalize_doc_number(doc.get(field)) for field in
                           ("bill_number", "expense_number", "credit_number", "reference_number")}
                for number in numbers - {""}:
                    if gstin:
                        books[(gstin, number, kind, bool(doc.get("reverse_charge")))].append(
                            (result, doc, category))

    matches: list[dict[str, Any]] = []
    used_portal: set[int] = set()
    used_books: set[int] = set()
    for key, portal_candidates in portal.items():
        books_candidates = books.get(key, [])
        # A single document may be indexed by both its number and reference.
        books_candidates = list({id(doc): (result, doc, category)
                                 for result, doc, category in books_candidates}.values())
        if len(portal_candidates) != 1 or len(books_candidates) != 1:
            continue
        portal_result, g_doc = portal_candidates[0]
        books_result, b_doc, category = books_candidates[0]
        if (portal_result is books_result or id(g_doc) in used_portal
                or id(b_doc) in used_books):
            continue
        if abs(float(g_doc["total_value"]) - float(b_doc["total"])) > tolerance:
            continue
        if abs(float(g_doc["tax_total"]) - float(b_doc["tax_total"])) > tolerance:
            continue
        used_portal.add(id(g_doc))
        used_books.add(id(b_doc))
        p_month = portal_result["metadata"]["target_month"]
        b_month = books_result["metadata"]["target_month"]
        portal_result["reconciliation"]["missing_in_books"].remove(g_doc)
        books_result["reconciliation"][category].remove(b_doc)
        portal_result["reconciliation"]["matched_documents"].append({
            "gstr2_doc": g_doc, "books_doc": b_doc,
            "books_amount": b_doc["total"], "gstr2_amount": g_doc["total_value"],
            "gstr2_taxable": g_doc["taxable_value"], "gstr2_tax": g_doc["tax_total"],
            "books_taxable": b_doc.get("sub_total"), "books_tax": b_doc.get("tax_total"),
            "diff": round(float(b_doc["total"]) - float(g_doc["total_value"]), 2),
            "notes": f"Books {b_month}; portal {p_month}",
        })
        match = {"books_month": b_month, "portal_month": p_month,
                 "supplier_gstin": key[0], "document_number": g_doc["doc_number"],
                 "document_type": key[2], "books_id": str(b_doc.get("bill_id") or
                 b_doc.get("expense_id") or b_doc.get("credit_id") or ""),
                 "total": g_doc["total_value"], "tax": g_doc["tax_total"]}
        matches.append(match)
        for result in (portal_result, books_result):
            result["reconciliation"].setdefault("cross_month_matches", []).append(match)

    for result in results:
        rec = result["reconciliation"]
        summary = rec["summary"]
        summary["matched_count"] = len(rec["matched_documents"]) + sum(
            item["count"] for item in rec["aggregate_matches"])
        summary["matched_tax"] = round(sum(item["gstr2_doc"]["tax_total"]
                                           for item in rec["matched_documents"]) +
                                       sum(item["tax"] for item in rec["aggregate_matches"]), 2)
        summary["missing_in_books_count"] = len(rec["missing_in_books"])
        summary["missing_in_books_tax"] = round(sum(item["tax_total"] for item in rec["missing_in_books"]), 2)
        for category, count_key, amount_key in (
            ("missing_in_gstr2_bills", "missing_in_gstr2_bills_count", "missing_in_gstr2_bills_amount"),
            ("missing_in_gstr2_expenses", "missing_in_gstr2_expenses_count", "missing_in_gstr2_expenses_amount"),
        ):
            summary[count_key] = len(rec[category])
            summary[amount_key] = round(sum(item["total"] for item in rec[category]), 2)
        # Books matches may belong to another month; this count describes the
        # portal month's matched documents in the annual adjusted report.
        summary["matched_books_count"] = len(rec["matched_documents"]) + len(rec["aggregate_matches"])
        for vendor in rec.get("vendor_summaries", []):
            gstin = str(vendor.get("gstin") or "").upper()
            vendor["missing_in_books_count"] = sum(
                doc.get("supplier_gstin", "").upper() == gstin for doc in rec["missing_in_books"])
            vendor["missing_in_gstr2_count"] = sum(
                doc.get("gst_no", "").upper() == gstin for cat in
                ("missing_in_gstr2_bills", "missing_in_gstr2_expenses") for doc in rec[cat])
            vendor["matched_count"] = sum(
                item["gstr2_doc"].get("supplier_gstin", "").upper() == gstin
                for item in rec["matched_documents"])
    return matches


def render_fiscal_year_missing_details(
    results: Sequence[Mapping[str, Any]], *, tolerance: float = 1.0,
) -> list[str]:
    """Render the unresolved document queue after cross-month matching."""
    def cell(value: Any) -> str:
        return str(value if value not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")

    def money(value: Any) -> str:
        return f"₹{float(value):,.2f}" if value not in (None, "") else "—"

    portal: list[tuple[str, Mapping[str, Any]]] = []
    books: list[tuple[str, str, Mapping[str, Any]]] = []
    mismatches: list[tuple[str, Mapping[str, Any]]] = []
    for result in results:
        month = str(result["metadata"]["target_month"])
        rec = result["reconciliation"]
        portal.extend((month, doc) for doc in rec["missing_in_books"])
        for key, kind in (("missing_in_gstr2_bills", "Bill"),
                          ("missing_in_gstr2_expenses", "Expense"),
                          ("missing_in_gstr2_credits", "Vendor credit")):
            books.extend((month, kind, doc) for doc in rec[key])
        mismatches.extend((month, item) for item in rec.get("value_mismatches", []))

    lines = ["", "## Unresolved Documents", "",
             "These rows remain after cross-month matches are removed. Review the source document and filing before changing Books or claiming ITC.", ""]
    overview_position = len(lines)
    by_supplier: dict[str, dict[str, Any]] = {}
    for _, doc in portal:
        key = str(doc.get("supplier_gstin") or doc.get("supplier_name") or "Unknown")
        item = by_supplier.setdefault(key, {"name": "", "gstin": doc.get("supplier_gstin") or "", "portal_count": 0,
                                            "portal_tax": 0.0, "books_count": 0,
                                            "books_tax": 0.0})
        item["name"] = item["name"] or str(doc.get("supplier_name") or "")
        item["portal_count"] += 1
        item["portal_tax"] += float(doc.get("tax_total") or 0)
    for _, _, doc in books:
        key = str(doc.get("gst_no") or doc.get("vendor_name") or "Unknown")
        item = by_supplier.setdefault(key, {"name": "", "gstin": doc.get("gst_no") or "", "portal_count": 0,
                                            "portal_tax": 0.0, "books_count": 0,
                                            "books_tax": 0.0})
        item["name"] = item["name"] or str(doc.get("vendor_name") or "")
        item["books_count"] += 1
        item["books_tax"] += float(doc.get("tax_total") or 0)
    lines.extend(["### Supplier review summary (including possible counterparts)", "",
                  "| Supplier | GSTIN | 2B only docs | 2B only GST | Books only docs | Books only GST |",
                  "| :--- | :--- | ---: | ---: | ---: | ---: |"])
    for gstin, item in sorted(by_supplier.items(),
                              key=lambda pair: -(pair[1]["portal_tax"] + pair[1]["books_tax"])):
        lines.append(f"| {cell(item['name'])} | {cell(item['gstin'])} | {item['portal_count']} | "
                     f"{money(item['portal_tax'])} | {item['books_count']} | "
                     f"{money(item['books_tax'])} |")
    if not by_supplier:
        lines.append("| — | — | 0 | ₹0.00 | 0 | ₹0.00 |")
    lines.append("")

    portal_numbers: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    books_numbers: dict[str, list[tuple[str, str, Mapping[str, Any]]]] = defaultdict(list)
    for row in portal:
        number = normalize_doc_number(row[1].get("doc_number"))
        if number:
            portal_numbers[number].append(row)
    for row in books:
        doc = row[2]
        numbers = {normalize_doc_number(doc.get(field)) for field in
                   ("bill_number", "expense_number", "credit_number", "reference_number")}
        for number in numbers - {""}:
            books_numbers[number].append(row)
    suggestions = []
    for number, portal_rows in portal_numbers.items():
        books_rows = books_numbers.get(number, [])
        if len(portal_rows) != 1 or len(books_rows) != 1:
            continue
        p_month, p_doc = portal_rows[0]
        b_month, b_kind, b_doc = books_rows[0]
        p_gstin = str(p_doc.get("supplier_gstin") or "").upper()
        b_gstin = str(b_doc.get("gst_no") or "").upper()
        if (not p_gstin or not b_gstin or p_gstin == b_gstin
                or (p_doc.get("doc_type") == "credit_note") != (b_kind == "Vendor credit")):
            continue
        if (b_doc.get("sub_total") in (None, "") or b_doc.get("tax_total") in (None, "")
                or abs(float(p_doc.get("taxable_value") or 0) - float(b_doc["sub_total"])) > tolerance
                or abs(float(p_doc.get("tax_total") or 0) - float(b_doc["tax_total"])) > tolerance):
            continue
        suggestions.append((p_month, b_month, p_doc, b_doc))
    suggested_portal_ids = {id(p_doc) for _, _, p_doc, _ in suggestions}
    suggested_books_ids = {id(b_doc) for _, _, _, b_doc in suggestions}
    portal = [row for row in portal if id(row[1]) not in suggested_portal_ids]
    books = [row for row in books if id(row[2]) not in suggested_books_ids]
    lines[overview_position:overview_position] = [
        "| Review queue | Documents or pairs | GST to review |",
        "| :--- | ---: | ---: |",
        f"| Possible counterparts with different GSTINs | {len(suggestions)} | {money(sum(float(p_doc.get('tax_total') or 0) for _, _, p_doc, _ in suggestions))} |",
        f"| In GSTR-2B, missing in Books (other) | {len(portal)} | {money(sum(float(doc.get('tax_total') or 0) for _, doc in portal))} |",
        f"| In Books, missing in GSTR-2B (other) | {len(books)} | {money(sum(float(doc.get('tax_total') or 0) for _, _, doc in books))} |",
        f"| Value mismatches | {len(mismatches)} | — |", "",
        "The monthly gap counts include the possible counterpart pairs; the detailed queues below show each pair only in its own group.", "",
    ]
    lines.extend([f"### Possible counterparts with different GSTINs ({len(suggestions)})", "",
                  "These share a unique document number, taxable value, and GST. They remain open; verify the supplier GSTIN and original document before resolving either gap.", "",
                  "| Document | Portal Month | Books Month | Portal GSTIN | Books GSTIN | Taxable | GST | Books ID |",
                  "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | :--- |"])
    for p_month, b_month, p_doc, b_doc in suggestions:
        book_id = b_doc.get("bill_id") or b_doc.get("expense_id") or b_doc.get("credit_id")
        lines.append(f"| {cell(p_doc.get('doc_number'))} | {p_month} | {b_month} | "
                     f"{cell(p_doc.get('supplier_gstin'))} | {cell(b_doc.get('gst_no'))} | "
                     f"{money(p_doc.get('taxable_value'))} | {money(p_doc.get('tax_total'))} | "
                     f"{cell(book_id)} |")
    if not suggestions:
        lines.append("| — | — | — | — | — | — | — | — |")
    lines.append("")
    lines.extend([f"### In GSTR-2B, missing in Books ({len(portal)})", "",
                  "| Portal Month | Supplier | GSTIN | Type | Document | Document Date | Taxable | GST | Total | RCM | Action |",
                  "| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |"])
    for month, doc in portal:
        action = ("Check for an unrecorded vendor credit or number/date difference"
                  if doc.get("doc_type") == "credit_note" else
                  "Check for an unrecorded purchase or number/date difference")
        lines.append(
            f"| {month} | {cell(doc.get('supplier_name'))} | {cell(doc.get('supplier_gstin'))} | "
            f"{cell(doc.get('doc_type'))} | {cell(doc.get('doc_number'))} | {cell(doc.get('doc_date'))} | "
            f"{money(doc.get('taxable_value'))} | {money(doc.get('tax_total'))} | "
            f"{money(doc.get('total_value'))} | {'Yes' if doc.get('reverse_charge') else 'No'} | "
            f"{action} |"
        )
    if not portal:
        lines.append("| — | — | — | — | — | — | — | — | — | — | None |")

    lines.extend(["", f"### In Books, missing in GSTR-2B ({len(books)})", "",
                  "| Books Month | Type | Supplier | GSTIN | Document | Reference | Date | Taxable | GST | Total | Books ID | Action |",
                  "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |"])
    for month, kind, doc in books:
        number = (doc.get("bill_number") or doc.get("expense_number")
                  or doc.get("credit_number"))
        doc_id = doc.get("bill_id") or doc.get("expense_id") or doc.get("credit_id")
        lines.append(
            f"| {month} | {kind} | {cell(doc.get('vendor_name'))} | {cell(doc.get('gst_no'))} | "
            f"{cell(number)} | {cell(doc.get('reference_number'))} | {cell(doc.get('date'))} | "
            f"{money(doc.get('sub_total'))} | {money(doc.get('tax_total'))} | "
            f"{money(doc.get('total'))} | {cell(doc_id)} | "
            "Check supplier filing, document number and ITC eligibility |"
        )
    if not books:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | None |")

    lines.extend(["", f"### Value mismatches ({len(mismatches)})", "",
                  "| Month | Supplier | GSTIN | Portal Document | Books Document | Portal Date | Portal Taxable | Books Taxable | Portal GST | Books GST | Portal Total | Books Total | Difference | Action |",
                  "| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"])
    for month, item in mismatches:
        portal_doc = item["gstr2_doc"]
        books_doc = item["books_doc"]
        number = (books_doc.get("bill_number") or books_doc.get("expense_number")
                  or books_doc.get("credit_number") or books_doc.get("reference_number"))
        lines.append(
            f"| {month} | {cell(portal_doc.get('supplier_name'))} | "
            f"{cell(portal_doc.get('supplier_gstin'))} | {cell(portal_doc.get('doc_number'))} | "
            f"{cell(number)} | {cell(portal_doc.get('doc_date'))} | "
            f"{money(item.get('gstr2_taxable'))} | {money(item.get('books_taxable'))} | "
            f"{money(item.get('gstr2_tax'))} | {money(item.get('books_tax'))} | "
            f"{money(item.get('gstr2_amount'))} | {money(item.get('books_amount'))} | "
            f"{money(item.get('diff'))} | Compare source invoice with Books tax and total |"
        )
    if not mismatches:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | — | None |")
    return lines + [""]
