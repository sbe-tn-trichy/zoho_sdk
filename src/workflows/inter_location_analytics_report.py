"""SQL and sync workflow for a live Analytics view of clearing-account contra location differences."""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple


def build_inter_location_query(account_id: str) -> str:
    """Return one row per cross-location customer/vendor or customer/journal pair."""
    if not account_id.isdecimal():
        raise ValueError("account_id must be a numeric Zoho Books ID")
    period = "CP.\"Payment Date\" >= '2025-04-01' AND CP.\"Payment Date\" <= '2027-03-31'"
    fy = "CASE WHEN CP.\"Payment Date\" < '2026-04-01' THEN 'FY 2025-26' ELSE 'FY 2026-27' END"
    return f'''
SELECT CP."Payment Date" AS "Date", {fy} AS "Financial Year",
 CP."Amount (BCY)" AS "Amount", 'Customer Payment' AS "Debit Type",
 CP."Payment ID" AS "Debit Transaction ID", DL."Location Name" AS "Debit Location",
 CP."Location ID" AS "Debit Location ID", CP."Reference Number" AS "Debit Reference",
 'Vendor Payment' AS "Credit Type", VP."Vendor Payment ID" AS "Credit Transaction ID",
 CL."Location Name" AS "Credit Location", VP."Location ID" AS "Credit Location ID",
 VP."Reference Number" AS "Credit Reference",
 CASE WHEN CP."Reference Number" IS NULL OR CP."Reference Number" = ''
 THEN 'Verify pairing' ELSE 'Exact reference' END AS "Matching Evidence"
FROM "Customer Payments (Zoho Books)" CP
JOIN "Vendor Payments (Zoho Books)" VP
 ON CP."Payment Date" = VP."Payment Date" AND CP."Amount (BCY)" = VP."Amount (BCY)"
LEFT JOIN "Locations (Zoho Books)" DL ON CP."Location ID" = DL."Location ID"
LEFT JOIN "Locations (Zoho Books)" CL ON VP."Location ID" = CL."Location ID"
WHERE CP."Account ID" = {account_id} AND VP."Account ID" = {account_id}
 AND CP."Location ID" <> VP."Location ID" AND {period}
 AND ((CP."Reference Number" = VP."Reference Number" AND CP."Reference Number" IS NOT NULL
       AND CP."Reference Number" <> '')
      OR ((CP."Reference Number" IS NULL OR CP."Reference Number" = '')
          AND (VP."Reference Number" IS NULL OR VP."Reference Number" = '')))
UNION ALL
SELECT CP."Payment Date" AS "Date", {fy} AS "Financial Year",
 CP."Amount (BCY)" AS "Amount", 'Customer Payment' AS "Debit Type",
 CP."Payment ID" AS "Debit Transaction ID", DL."Location Name" AS "Debit Location",
 CP."Location ID" AS "Debit Location ID", CP."Reference Number" AS "Debit Reference",
 'Journal' AS "Credit Type", JI."Journal ID" AS "Credit Transaction ID",
 CL."Location Name" AS "Credit Location", JI."Location ID" AS "Credit Location ID",
 MJ."Reference" AS "Credit Reference", 'Verify pairing' AS "Matching Evidence"
FROM "Customer Payments (Zoho Books)" CP
JOIN "Manual Journal Items (Zoho Books)" JI
 ON CP."Amount (BCY)" = JI."Total (BCY)"
JOIN "Manual Journals (Zoho Books)" MJ
 ON JI."Journal ID" = MJ."Journal ID" AND CP."Payment Date" = MJ."Journal Date"
LEFT JOIN "Locations (Zoho Books)" DL ON CP."Location ID" = DL."Location ID"
LEFT JOIN "Locations (Zoho Books)" CL ON JI."Location ID" = CL."Location ID"
WHERE CP."Account ID" = {account_id} AND JI."Account ID" = {account_id}
 AND JI."Debit or Credit" = 'credit' AND CP."Location ID" <> JI."Location ID"
 AND {period} AND (CP."Reference Number" IS NULL OR CP."Reference Number" = '')
'''.strip()


def build_inter_location_document_query(account_id: str) -> str:
    """Add source documents and all bank-account payment allocation differences."""
    base = build_inter_location_query(account_id)
    return f'''
SELECT BASE.*, IP."Invoice ID" AS "Invoice ID", I."Invoice Number" AS "Invoice Number",
 IL."Location Name" AS "Invoice Location", I."Location ID" AS "Invoice Location ID",
 PM."Bill ID" AS "Bill ID", B."Bill Number" AS "Bill Number",
 BL."Location Name" AS "Bill Location", B."Location ID" AS "Bill Location ID",
 CASE WHEN B."Bill ID" IS NULL THEN 'No allocated bill'
      WHEN I."Location ID" = B."Location ID" THEN 'Invoice and bill agree'
      ELSE 'Invoice and bill differ' END AS "Document Location Check",
 'Contra pair' AS "Issue Type", {account_id} AS "Bank Account ID",
 A."Account Name" AS "Bank Account Name"
FROM ({base}) BASE
JOIN "Accounts (Zoho Books)" A ON A."Account ID" = {account_id}
LEFT JOIN "Invoice Payments (Zoho Books)" IP
 ON BASE."Debit Transaction ID" = IP."Payment ID"
LEFT JOIN "Invoices (Zoho Books)" I ON IP."Invoice ID" = I."Invoice ID"
LEFT JOIN "Locations (Zoho Books)" IL ON I."Location ID" = IL."Location ID"
LEFT JOIN "Payments Made (Zoho Books)" PM
 ON BASE."Credit Type" = 'Vendor Payment' AND BASE."Credit Transaction ID" = PM."Vendor Payment ID"
LEFT JOIN "Bills (Zoho Books)" B ON PM."Bill ID" = B."Bill ID"
LEFT JOIN "Locations (Zoho Books)" BL ON B."Location ID" = BL."Location ID"
UNION ALL
SELECT CP."Payment Date" AS "Date",
 CASE WHEN CP."Payment Date" < '2026-04-01' THEN 'FY 2025-26' ELSE 'FY 2026-27' END AS "Financial Year",
 CP."Amount (BCY)" AS "Amount", 'Customer Payment' AS "Debit Type",
 CP."Payment ID" AS "Debit Transaction ID", PL."Location Name" AS "Debit Location",
 CP."Location ID" AS "Debit Location ID", CP."Reference Number" AS "Debit Reference",
 'Invoice' AS "Credit Type", I."Invoice ID" AS "Credit Transaction ID",
 IL."Location Name" AS "Credit Location", I."Location ID" AS "Credit Location ID",
 I."Invoice Number" AS "Credit Reference", 'Allocation' AS "Matching Evidence",
 I."Invoice ID" AS "Invoice ID", I."Invoice Number" AS "Invoice Number",
 IL."Location Name" AS "Invoice Location", I."Location ID" AS "Invoice Location ID",
 NULL AS "Bill ID", NULL AS "Bill Number", NULL AS "Bill Location",
 NULL AS "Bill Location ID", 'Payment and invoice differ' AS "Document Location Check",
 'Customer payment vs invoice' AS "Issue Type", CP."Account ID" AS "Bank Account ID",
 A."Account Name" AS "Bank Account Name"
FROM "Customer Payments (Zoho Books)" CP
JOIN "Accounts (Zoho Books)" A ON CP."Account ID" = A."Account ID"
JOIN "Invoice Payments (Zoho Books)" IP ON CP."Payment ID" = IP."Payment ID"
JOIN "Invoices (Zoho Books)" I ON IP."Invoice ID" = I."Invoice ID"
LEFT JOIN "Locations (Zoho Books)" PL ON CP."Location ID" = PL."Location ID"
LEFT JOIN "Locations (Zoho Books)" IL ON I."Location ID" = IL."Location ID"
WHERE A."Account Type" = 'Bank'
 AND CP."Payment Date" >= '2025-04-01' AND CP."Payment Date" <= '2027-03-31'
 AND CP."Location ID" <> I."Location ID"
UNION ALL
SELECT VP."Payment Date" AS "Date",
 CASE WHEN VP."Payment Date" < '2026-04-01' THEN 'FY 2025-26' ELSE 'FY 2026-27' END AS "Financial Year",
 VP."Amount (BCY)" AS "Amount", 'Vendor Payment' AS "Debit Type",
 VP."Vendor Payment ID" AS "Debit Transaction ID", PL."Location Name" AS "Debit Location",
 VP."Location ID" AS "Debit Location ID", VP."Reference Number" AS "Debit Reference",
 'Bill' AS "Credit Type", B."Bill ID" AS "Credit Transaction ID",
 BL."Location Name" AS "Credit Location", B."Location ID" AS "Credit Location ID",
 B."Bill Number" AS "Credit Reference", 'Allocation' AS "Matching Evidence",
 NULL AS "Invoice ID", NULL AS "Invoice Number", NULL AS "Invoice Location",
 NULL AS "Invoice Location ID", B."Bill ID" AS "Bill ID", B."Bill Number" AS "Bill Number",
 BL."Location Name" AS "Bill Location", B."Location ID" AS "Bill Location ID",
 'Payment and bill differ' AS "Document Location Check",
 'Vendor payment vs bill' AS "Issue Type", VP."Account ID" AS "Bank Account ID",
 A."Account Name" AS "Bank Account Name"
FROM "Vendor Payments (Zoho Books)" VP
JOIN "Accounts (Zoho Books)" A ON VP."Account ID" = A."Account ID"
JOIN "Payments Made (Zoho Books)" PM ON VP."Vendor Payment ID" = PM."Vendor Payment ID"
JOIN "Bills (Zoho Books)" B ON PM."Bill ID" = B."Bill ID"
LEFT JOIN "Locations (Zoho Books)" PL ON VP."Location ID" = PL."Location ID"
LEFT JOIN "Locations (Zoho Books)" BL ON B."Location ID" = BL."Location ID"
WHERE A."Account Type" = 'Bank'
 AND VP."Payment Date" >= '2025-04-01' AND VP."Payment Date" <= '2027-03-31'
 AND VP."Location ID" <> B."Location ID"
'''.strip()


def validate_document_rows(rows: list[dict]) -> set[tuple[str, str]]:
    """Check that the report contains different payment locations and source documents."""
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        debit_location = str(row.get("Debit Location ID") or "")
        credit_location = str(row.get("Credit Location ID") or "")
        if not debit_location or not credit_location or debit_location == credit_location:
            raise ValueError("Report contains a pair without two different locations")
        issue = row.get("Issue Type") or "Contra pair"
        if issue not in {"Contra pair", "Customer payment vs invoice", "Vendor payment vs bill"}:
            raise ValueError(f"Unknown location issue type: {issue}")
        if issue != "Vendor payment vs bill" and (not row.get("Invoice ID") or not row.get("Invoice Location ID")):
            raise ValueError("Report contains a pair without a source invoice location")
        if (issue == "Vendor payment vs bill" or
            (issue == "Contra pair" and row.get("Credit Type") == "Vendor Payment")) and (
            not row.get("Bill ID") or not row.get("Bill Location ID")
        ):
            raise ValueError("Vendor payment pair lacks a source bill location")
        pairs.add((str(row["Debit Transaction ID"]), str(row["Credit Transaction ID"])))
    if not pairs:
        raise ValueError("No inter-location pairs found")
    return pairs


def sync_inter_location_contra_query_table(
    analytics: Any,
    *,
    workspace_id: str,
    account_id: str = "1094368000002033114",
    view_id: Optional[str] = None,
    name: str = "Inter Location Contra FY25-27",
    apply: bool = False,
    description: str = "Live clearing-account contra pairs across locations, FY 2025-26 and FY 2026-27; blank references require pairing review.",
) -> Dict[str, Any]:
    """Single unified workflow function for previewing, creating, or updating the Analytics Query Table."""
    sql = build_inter_location_document_query(account_id)
    # The bulk SQL preview is a GET request. Preview the three UNION branches
    # separately so the encoded URL stays below the server's URI limit.
    branches = sql.rsplit("\nUNION ALL\n", 2)
    if len(branches) != 3:
        raise ValueError("Expected contra, customer allocation, and vendor allocation branches")
    preview = [row for branch in branches for row in analytics.queries.execute(workspace_id, branch)]
    expected_pairs = validate_document_rows(preview)

    result: Dict[str, Any] = {
        "sql": sql,
        "preview_row_count": len(preview),
        "validated_pair_count": len(expected_pairs),
        "applied": False,
        "view_id": view_id,
    }

    if not apply:
        return result

    if view_id:
        analytics.views.update_query_table(workspace_id, view_id, sql)
        target_view_id = view_id
    else:
        existing = [
            view for view in analytics.metadata.list_all_views(workspace_id)
            if view.get("viewName") == name
        ]
        if existing:
            raise ValueError(f"Query Table name already exists: {existing[0]['viewId']}")
        target_view_id = analytics.views.create_query_table(
            workspace_id, name, sql, description
        )
        result["view_id"] = target_view_id

    saved = analytics.views.export_all(workspace_id, target_view_id)
    if validate_document_rows(saved) != expected_pairs or len(saved) != len(preview):
        raise ValueError(f"Saved Query Table {target_view_id} differs from the validated preview")

    result["applied"] = True
    result["saved_row_count"] = len(saved)
    return result
