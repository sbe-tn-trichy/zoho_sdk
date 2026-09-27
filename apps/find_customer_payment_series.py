"""Find and analyze unique transaction number series for customer payments in Zoho Books using Zoho Analytics with FY filtering."""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_ROOT = Path("d:/workplace/zoho_sdk").resolve()
sys.path.insert(0, str(WORKSPACE_ROOT / "zoho_sdk" / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

try:
    from workflows.core.auth import get_analytics_client
except ImportError:
    from zoho import HttpTokenProvider, ZohoAnalyticsAPI

    def get_analytics_client():
        token_url = os.environ.get("TOKEN_URL", "http://localhost:3000/server/new/tokens")
        token = HttpTokenProvider(token_url).get_token("analytics")
        org_id = os.environ.get("ZOHO_ANALYTICS_ORGANIZATION_ID", "60018545708")
        domain = os.environ.get("ZOHO_ANALYTICS_DOMAIN", "com")
        return ZohoAnalyticsAPI(access_token=token, organization_id=org_id, domain=domain)


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse Zoho date strings into a datetime object."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def get_fy_date_range(fy_param: str, reference_date: Optional[datetime] = None) -> Tuple[datetime, datetime, str]:
    """Calculate start and end date for a given FY (Indian Financial Year: Apr 1 - Mar 31)."""
    ref = reference_date or datetime.now()
    # Determine current FY: If month >= 4 (Apr-Dec), FY is current_year to current_year+1
    current_fy_start_year = ref.year if ref.month >= 4 else ref.year - 1

    fy_clean = fy_param.lower().strip()
    if fy_clean in ("last", "prev", "previous", "last_fy", "last-fy"):
        start_year = current_fy_start_year - 1
    elif fy_clean in ("current", "this", "this_fy", "current_fy"):
        start_year = current_fy_start_year
    elif re.match(r"^(\d{2,4})[-/]?(\d{2,4})?$", fy_clean):
        # Format like 25-26, 2025-2026, 2025-26, 2526
        m = re.match(r"^(\d{2,4})[-/]?(\d{2,4})?$", fy_clean)
        y1_str = m.group(1)
        if len(y1_str) == 2:
            start_year = 2000 + int(y1_str)
        elif len(y1_str) == 4:
            if m.group(2) and len(m.group(2)) == 2:
                # e.g., 2425 or 2526 as a 4-digit string
                start_year = 2000 + int(y1_str[:2])
            else:
                start_year = int(y1_str)
        else:
            start_year = int(y1_str)
    else:
        # Default fallback to Last FY
        start_year = current_fy_start_year - 1

    start_date = datetime(start_year, 4, 1, 0, 0, 0)
    end_date = datetime(start_year + 1, 3, 31, 23, 59, 59)
    fy_label = f"FY {start_year}-{str(start_year + 1)[-2:]} (01/04/{start_year} to 31/03/{start_year + 1})"
    return start_date, end_date, fy_label


def fetch_customer_payments(workspace_id: str) -> List[Dict[str, Any]]:
    """Query customer payments from Zoho Analytics."""
    analytics = get_analytics_client()
    query = """
    SELECT 
        "Payment Number",
        "Payment Date",
        "Payment Mode",
        "Payment Status",
        "Amount (BCY)",
        "Location ID"
    FROM "Customer Payments (Zoho Books)"
    """
    return analytics.queries.execute(
        workspace_id=workspace_id,
        sql_query=query,
        max_attempts=30,
        poll_interval=2.0,
    )


def extract_series_info(records: List[Dict[str, Any]], start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], int]:
    """Group customer payments by transaction number series and filter by date range."""
    grouped = defaultdict(list)
    total_matched = 0

    for record in records:
        p_date = parse_date(record.get("Payment Date"))
        
        # Apply date filters
        if start_date and p_date and p_date < start_date:
            continue
        if end_date and p_date and p_date > end_date:
            continue
        if (start_date or end_date) and p_date is None:
            continue

        total_matched += 1
        payment_num = str(record.get("Payment Number") or "").strip()
        if not payment_num:
            prefix = "[EMPTY]"
            num_str = ""
            num_val = None
        else:
            match = re.match(r"^(.*?)(\d+)$", payment_num)
            if match:
                prefix, num_str = match.groups()
                num_val = int(num_str)
            else:
                prefix = payment_num
                num_str = ""
                num_val = None

        grouped[prefix].append({
            "full_number": payment_num,
            "num_str": num_str,
            "num_val": num_val,
            "date": p_date,
            "mode": record.get("Payment Mode") or "Unknown",
            "status": record.get("Payment Status") or "Unknown",
            "amount": record.get("Amount (BCY)"),
        })

    series_summary = []
    for prefix, items in sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True):
        count = len(items)
        num_vals = [it["num_val"] for it in items if it["num_val"] is not None]
        num_lengths = [len(it["num_str"]) for it in items if it["num_str"]]

        if num_vals:
            min_num = min(num_vals)
            max_num = max(num_vals)
            pad_len = max(num_lengths) if num_lengths else 0
            formatted_min = f"{min_num:0{pad_len}d}"
            formatted_max = f"{max_num:0{pad_len}d}"
            range_str = f"{formatted_min} - {formatted_max}"
            padding_desc = f"{pad_len} digits"
        else:
            min_num, max_num = None, None
            range_str = "Non-numeric"
            padding_desc = "N/A"

        dates = [it["date"] for it in items if it["date"] is not None]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            min_date_str = min_date.strftime("%d/%m/%Y")
            max_date_str = max_date.strftime("%d/%m/%Y")
            date_range_str = f"{min_date_str} to {max_date_str}"
        else:
            min_date_str, max_date_str = "N/A", "N/A"
            date_range_str = "N/A"

        modes = Counter(it["mode"] for it in items)
        top_modes = ", ".join(f"{k} ({v})" for k, v in modes.most_common(3))

        series_summary.append({
            "series_prefix": prefix if prefix != "" else "[Numeric Only]",
            "raw_prefix": prefix,
            "count": count,
            "min_number": min_num,
            "max_number": max_num,
            "number_range": range_str,
            "digit_padding": padding_desc,
            "start_date": min_date_str,
            "end_date": max_date_str,
            "date_range": date_range_str,
            "sample_first": items[0]["full_number"],
            "sample_last": items[-1]["full_number"],
            "top_modes": top_modes,
        })

    return series_summary, total_matched


def display_results(series_list: List[Dict[str, Any]], total_records: int, filter_title: str):
    """Print results formatted as a table."""
    print("=" * 115)
    print(f" ZOHO BOOKS CUSTOMER PAYMENTS - {filter_title.upper()}")
    print("=" * 115)
    print(f"Transactions in this Period : {total_records:,}")
    print(f"Unique Series in Period     : {len(series_list)}")
    print("-" * 115)
    print(
        f"{'#':<3} | {'Series Prefix':<16} | {'Count':>7} | {'Range':<15} | {'Date Range':<23} | {'Sample Transaction'}"
    )
    print("-" * 115)

    for idx, s in enumerate(series_list, 1):
        print(
            f"{idx:<3} | {s['series_prefix']:<16} | {s['count']:>7,d} | {s['number_range']:<15} | {s['date_range']:<23} | {s['sample_first']}"
        )

    print("=" * 115)


def main():
    parser = argparse.ArgumentParser(
        description="Filter and analyze unique transaction number series for customer payments in Zoho Books."
    )
    parser.add_argument(
        "--fy",
        default="last",
        help="Financial Year filter: 'last' (default), 'current', '25-26', '24-25', '23-24', etc.",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("ZOHO_ANALYTICS_WORKSPACE_ID", "264324000000002043"),
        help="Zoho Analytics workspace ID",
    )
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE_ROOT / "output"),
        help="Directory to save outputs",
    )
    args = parser.parse_args()

    start_date, end_date, fy_label = get_fy_date_range(args.fy)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug_fy = fy_label.split()[1].replace("-", "_").lower()
    json_path = out_dir / f"customer_payment_series_{slug_fy}.json"

    print(f"Connecting to Zoho Analytics (Workspace ID: {args.workspace_id})...")
    print(f"Filtering for: {fy_label}")
    records = fetch_customer_payments(workspace_id=args.workspace_id)
    series_info, matched_count = extract_series_info(records, start_date=start_date, end_date=end_date)

    display_results(series_info, matched_count, filter_title=f"Transaction Number Series for {fy_label}")

    # Save to JSON
    json_data = {
        "financial_year": fy_label,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "total_period_records": matched_count,
        "total_series": len(series_info),
        "series": series_info,
    }
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    print(f"\n[OK] JSON exported to: {json_path}")


if __name__ == "__main__":
    main()
