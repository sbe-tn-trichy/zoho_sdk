"""Report generation for Neoseal item audit."""

from __future__ import annotations

from typing import Mapping

from .auditor import NeosealAuditResult


def render_markdown_report(result: NeosealAuditResult, metadata: Mapping[str, str] | None = None) -> str:
    """Render a GitHub-flavored Markdown report from audit results."""
    meta = metadata or {}
    source_label = meta.get("source", "Zoho Books API")
    timestamp = meta.get("checked_at", "N/A")

    lines: list[str] = [
        "# Neoseal Inventory Item Audit & Nomenclature Report",
        "",
        f"- **Audited At:** {timestamp}",
        f"- **Data Source:** {source_label}",
        f"- **Total Items:** {result['total_audited']} (Active: {result['active_count']}, Inactive: {result['inactive_count']})",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        "| Audit Check | Status | Issues Found | Focus / Recommendation |",
        "| :--- | :---: | :---: | :--- |",
        (
            f"| **1. Duplicates & Twins** | {'⚠️ Warning' if result['duplicates'] else '✅ Clean'} | "
            f"{len(result['duplicates'])} | Flagged packaging twins (Tin vs Can) & legacy duplicates |"
        ),
        (
            f"| **2. Naming Nomenclature** | {'⚠️ Warning' if result['naming_issues'] else '✅ Clean'} | "
            f"{len(result['naming_issues'])} | Standardize Title Case (`GS Plus`, parenthetical tape colors) |"
        ),
        (
            f"| **3. User-Generated SKUs** | {'⚠️ Warning' if result['sku_issues'] else '✅ Clean'} | "
            f"{len(result['sku_issues'])} | Solvent structure inversion & missing chemical unit suffixes |"
        ),
        (
            f"| **4. Group Categorization** | {'⚠️ Warning' if result['group_issues'] else '✅ Clean'} | "
            f"{len(result['group_issues'])} | Unassigned Zoho item groups & catch-all buckets |"
        ),
        "",
        "---",
        "",
        "## 1. Duplicates & Twin Variants",
        "",
    ]

    if not result["duplicates"]:
        lines.append("No duplicate items or high-risk twin variants detected.")
    else:
        lines.append("| Type | Item A (Status / SKU / Stock) | Item B (Status / SKU / Stock) | Risk / Details |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for d in result["duplicates"]:
            a = d["item_a"]
            b = d["item_b"]
            str_a = f"`{a['name']}`<br>({a['status']}, SKU: `{a['sku']}`, Stock: {a['stock_on_hand']})"
            str_b = f"`{b['name']}`<br>({b['status']}, SKU: `{b['sku']}`, Stock: {b['stock_on_hand']})"
            lines.append(f"| **{d['match_type'].replace('_', ' ').title()}** | {str_a} | {str_b} | {d['details']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Item Naming Nomenclature Issues",
        "",
    ])

    if not result["naming_issues"]:
        lines.append("All item names follow standard naming conventions.")
    else:
        lines.append("| Current Name | Current SKU | Issue Description | Recommended Name |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for issue in result["naming_issues"]:
            lines.append(
                f"| `{issue['name']}` | `{issue['sku']}` | {issue['description']} | **`{issue['recommendation']}`** |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 3. User-Generated SKU Nomenclature Issues",
        "",
    ])

    if not result["sku_issues"]:
        lines.append("All user-generated SKUs follow standard formula conventions.")
    else:
        lines.append("| Item Name | Current SKU | Issue Type | Recommendation | Details |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for issue in result["sku_issues"]:
            lines.append(
                f"| `{issue['name']}` | `{issue['sku']}` | {issue['issue_type']} | "
                f"**`{issue['recommendation']}`** | {issue['description']} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 4. Group Assignment & Categorization Issues",
        "",
    ])

    if not result["group_issues"]:
        lines.append("All items are properly grouped in Zoho.")
    else:
        lines.append("| Item Name | SKU | Current Group | Issue | Recommended Target Group |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for issue in result["group_issues"]:
            curr = f"`{issue['current_group']}`" if issue['current_group'] else "*None (unassigned)*"
            lines.append(
                f"| `{issue['name']}` | `{issue['sku']}` | {curr} | {issue['description']} | "
                f"**`{issue['recommended_group']}`** |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## Action Checklist",
        "",
        "- [ ] Replace `GS PLUS` with `GS Plus` across all 7 PVC Ball Valves.",
        "- [ ] Update `PTFE Tape Premium 12mm 5mtr Yellow` (`5M-YELLOW-12MM`) to White (`5M-WHITE-12MM`).",
        "- [ ] Standardize Insulation Tape parentheses casing to Title Case (e.g. `(Blue)`, `(Green)`, `(Red)`).",
        "- [ ] Re-index SKU `20-PVC-UPVC-CLR-TUBE` to `UPVC-20-CLR-TUBE` and reassign from `Solvent Others` to `UPVC Solvent`.",
        "- [ ] Assign unassigned accounting helper `Solvent Rate Difference` (`Neoseal CN`) to `Neoseal Adjustment`.",
        "- [ ] Append explicit unit suffixes to chemical SKUs (`501-1KG`, `514-10KG`, `507-10L`, `IWP-500-1L`, `518-300G`).",
        "",
    ])

    return "\n".join(lines)
