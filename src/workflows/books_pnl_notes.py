"""Prepare the reviewed FY P&L note inputs from one Books report."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from zoho.helpers import fetch_profit_and_loss_schedule_format


NOTE_SHEET = "Notes to P & L 19 to 25"
NOTE_INPUTS = (
    "G6", "G9", "G15", "G18", "G45", "G46", "G69", "G76", "G79",
    "G85", "G92", "G93", "G95", "G99", "G101", "G102", "G103",
    "G107", "G114",
)


def prepare_pnl_note_updates(
    books: Any,
    *,
    from_date: str,
    to_date: str,
    excluded_location_id: str,
    account_groups: Mapping[str, list[str]],
    partner_interest: Decimal,
) -> dict[str, Decimal]:
    """Return note inputs, checking all seven note totals against Books.

    The partner-interest amount comes from Note 3, which the equity workflow
    maintains. Account groups contain stable Books account IDs for reviewed
    classifications; G9, G46, G76 and G114 are disclosed remainders.
    """
    report = fetch_profit_and_loss_schedule_format(
        books, from_date=from_date, to_date=to_date,
        excluded_location_id=excluded_location_id,
    )
    if not isinstance(partner_interest, Decimal) or not partner_interest.is_finite():
        raise ValueError("partner_interest must be a finite Decimal")
    groups: dict[str, dict[str, Decimal]] = {}
    for parent in report.get("profit_and_loss", []):
        for section in parent.get("account_transactions", []):
            if section.get("name") in {
                "Operating Income", "Cost of Goods Sold", "Operating Expense",
                "Non Operating Income", "Non Operating Expense",
            }:
                section_name = section["name"]
                groups[section_name] = {}
                for account in section.get("account_transactions", []):
                    account_id = str(account.get("account_id") or "")
                    if account_id in groups[section_name]:
                        raise ValueError(f"Duplicate Books account: {account_id}")
                    groups[section_name][account_id] = Decimal(str(account["total"]))
    required = {"Operating Income", "Cost of Goods Sold", "Operating Expense", "Non Operating Income"}
    if not required <= groups.keys():
        raise ValueError("Books P&L is missing a required section")

    def total(section: str) -> Decimal:
        return sum(groups[section].values(), Decimal())

    def mapped(cell: str, section: str) -> Decimal:
        ids = account_groups.get(cell)
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
            raise ValueError(f"Missing or duplicate account IDs for {cell}")
        missing = set(ids) - groups[section].keys()
        if missing:
            raise ValueError(f"Books {section} is missing mapped IDs for {cell}: {sorted(missing)}")
        return sum((groups[section][account_id] for account_id in ids), Decimal())

    gross_interest = mapped("interest_expense", "Operating Expense")
    if not Decimal() <= partner_interest <= gross_interest:
        raise ValueError("Partner interest does not fit Books interest expense")
    values = {
        "G6": mapped("G6", "Operating Income"),
        "G15": mapped("G15", "Operating Income"),
        "G18": total("Non Operating Income"),
        "G45": mapped("G45", "Cost of Goods Sold"),
        "G69": mapped("G69", "Operating Expense"),
        "G79": partner_interest,
        "G85": mapped("G85", "Operating Expense"),
    }
    values["G9"] = total("Operating Income") - values["G6"] - values["G15"]
    values["G46"] = total("Cost of Goods Sold") - values["G45"]
    values["G76"] = gross_interest - partner_interest
    for cell in ("G92", "G93", "G95", "G99", "G101", "G102", "G103", "G107"):
        values[cell] = mapped(cell, "Operating Expense")
    classified = sum((values[cell] for cell in (
        "G69", "G76", "G79", "G85", "G92", "G93", "G95", "G99",
        "G101", "G102", "G103", "G107",
    )), Decimal())
    values["G114"] = total("Operating Expense") - classified
    if set(values) != set(NOTE_INPUTS):
        raise ValueError("P&L note mapping is incomplete")
    if sum((values[c] for c in ("G6", "G9", "G15")), Decimal()) != total("Operating Income"):
        raise ValueError("Operating income does not reconcile")
    if values["G45"] + values["G46"] != total("Cost of Goods Sold"):
        raise ValueError("Cost of goods sold does not reconcile")
    if sum((values[c] for c in ("G69", "G76", "G79", "G85", "G92", "G93", "G95", "G99", "G101", "G102", "G103", "G107", "G114")), Decimal()) != total("Operating Expense"):
        raise ValueError("Operating expense does not reconcile")
    return {f"'{NOTE_SHEET}'!{cell}": values[cell] for cell in NOTE_INPUTS}
