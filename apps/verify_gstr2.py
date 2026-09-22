#!/usr/bin/env python3
"""Cross-check GSTR-2 / GSTR-2B JSON returns against Zoho Books purchases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client
from workflows.core.config import Config
from workflows.gstr2_verification import (
    GSTR2VerificationConfig,
    render_markdown_report,
    verify_gstr2,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "json_file",
        nargs="?",
        default=r"C:\Users\VAK\Downloads\returns_R2B_33AATFB2164K1Z9_042025.json",
        help="Path to the GSTR-2 / GSTR-2B JSON file",
    )
    parser.add_argument(
        "--json-path",
        dest="explicit_json_path",
        help="Explicit path to GSTR-2 / GSTR-2B JSON file (overrides positional)",
    )
    parser.add_argument(
        "--month",
        help="Target month 'YYYY-MM' (if omitted, extracted from JSON return period)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="Amount difference tolerance in INR (default: 1.00)",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include draft bills from Zoho Books in reconciliation",
    )
    parser.add_argument(
        "--org-id",
        default=Config.ORG_ID,
        help="Zoho Books organization ID",
    )
    parser.add_argument(
        "--domain",
        default=Config.DOMAIN,
        help="Zoho data-center domain",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/gstr2_verification_042025.md"),
        help="Path to write the markdown reconciliation report",
    )
    parser.add_argument(
        "--lookup",
        help="Search Zoho Books for item HSN/SAC, bills, or credits matching a query (e.g. DA2524)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    print("Connecting to Zoho Books...")
    books = get_books_client(org_id=args.org_id, domain=args.domain)

    if args.lookup:
        print(f"\nLooking up HSN / line items for '{args.lookup}' in Zoho Books...")
        verifier = GSTR2Verifier(books)
        lookup_result = verifier.lookup_hsn(args.lookup)
        
        found = False
        if lookup_result["bills"]:
            found = True
            print("\n=== MATCHING BILLS ===")
            for b in lookup_result["bills"]:
                print(f"Bill #{b['bill_number']} | Date: {b['date']} | Total: Rs. {b['total']} | Vendor: {b['vendor_name']}")
                for it in b["items"]:
                    print(f"  -> Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']} | Tax: {it['tax_name']} ({it['tax_percentage']}%)")

        if lookup_result["vendor_credits"]:
            found = True
            print("\n=== MATCHING VENDOR CREDITS ===")
            for c in lookup_result["vendor_credits"]:
                print(f"Credit #{c['credit_number']} | Ref: {c['reference_number']} | Date: {c['date']} | Total: Rs. {c['total']} | Vendor: {c['vendor_name']}")
                for it in c["items"]:
                    print(f"  -> Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if lookup_result["contacts"]:
            found = True
            print("\n=== MATCHING VENDORS / CONTACTS ===")
            for ct in lookup_result["contacts"]:
                print(f"Vendor: {ct['contact_name']} | GSTIN: {ct['gst_no']} | Bills in Books: {ct['bills_count']}")
                for it in ct["sample_items"]:
                    print(f"  -> Bill #{it['bill_number']} ({it['date']}): {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if lookup_result["items"]:
            found = True
            print("\n=== MATCHING ITEMS IN CATALOG ===")
            for it in lookup_result["items"]:
                print(f"Item: {it['name']} | HSN/SAC: {it['hsn_or_sac']} | Rate: {it['rate']}")

        if not found:
            print(f"No records or items found matching '{args.lookup}' in Zoho Books.")
        return 0

    json_path = args.explicit_json_path or args.json_file
    if not json_path:
        print("Error: Please provide a GSTR-2B JSON file path.", file=sys.stderr)
        return 1

    path_obj = Path(json_path)
    if not path_obj.exists():
        print(f"Error: File not found at '{path_obj}'", file=sys.stderr)
        return 1

    print(f"Loading GSTR-2B data from: {path_obj}")

    config = GSTR2VerificationConfig(
        amount_tolerance=args.tolerance,
        include_drafts=args.include_drafts,
    )

    print("Running GSTR-2B verification against Zoho Books...")
    result = verify_gstr2(
        books_client=books,
        gstr2_source=path_obj,
        month=args.month,
        config=config,
    )

    # Render and save report
    report_md = render_markdown_report(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report_md, encoding="utf-8")
    print(f"\nReconciliation report written to: {args.output.resolve()}")

    # Print summary to terminal
    meta = result["metadata"]
    rec = result["reconciliation"]
    summary = rec["summary"]

    print("\n" + "=" * 70)
    print(f"GSTR-2B vs Zoho Books Verification Summary ({meta['target_month']})")
    print("=" * 70)
    print(f"Recipient GSTIN:       {meta['recipient_gstin']}")
    print(f"Portal Return Period:  {meta['return_period']}")
    print(f"GSTR-2B Documents:     {summary['gstr2_total_docs']} (Total Value: Rs. {summary['gstr2_total_value']:,.2f})")
    print(f"GSTR-2B Eligible ITC:  Rs. {summary['gstr2_total_tax']:,.2f} (Taxable: Rs. {summary['gstr2_total_taxable']:,.2f})")
    print(f"  - IGST:              Rs. {summary['gstr2_total_igst']:,.2f}")
    print(f"  - CGST:              Rs. {summary['gstr2_total_cgst']:,.2f}")
    print(f"  - SGST:              Rs. {summary['gstr2_total_sgst']:,.2f}")
    print("-" * 70)
    print(f"Books Bills Fetched:   {summary['books_total_bills_count']} (Total Amount: Rs. {summary['books_total_bills_amount']:,.2f})")
    print(f"Books Credits Fetched: {summary['books_total_credits_count']} (Total Amount: Rs. {summary['books_total_credits_amount']:,.2f})")
    print("-" * 70)
    print(f"Fully Matched Invoices:{summary['matched_count']} (ITC: Rs. {summary['matched_tax']:,.2f})")
    print(f"Value Mismatches:      {summary['value_mismatch_count']}")
    print(f"Missing in Books:      {summary['missing_in_books_count']} (Portal ITC: Rs. {summary['missing_in_books_tax']:,.2f})")
    print(f"Missing in GSTR-2B:    {summary['missing_in_gstr2_bills_count']} (Taxable Total: Rs. {summary['missing_in_gstr2_bills_amount']:,.2f}) [ITC AT RISK]")
    print(f"Zero-Tax Bills:        {summary.get('zero_tax_bills_count', 0)} [No GSTR-2 ITC Impact]")
    print(f"Ineligible ITC:        {summary['ineligible_itc_count']}")
    print(f"Reverse Charge (RCM):  {summary['rcm_count']}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
