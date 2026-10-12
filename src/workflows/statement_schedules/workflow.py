"""Prepare configured note schedules and Sheets formulas without mutating Books."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from workflows.core.matching import to_finite_decimal
from workflows.financial_statement_comparison.comparison import fetch_schedule_reports

KEYS = {"balancesheet": "schedule_balance_sheet", "profitandloss": "schedule_profit_and_loss"}


def amount(value: Any) -> Decimal:
    result = to_finite_decimal(value, allow_commas=True)
    if result is None:
        raise ValueError(f"Invalid financial amount: {value!r}")
    return result


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def nodes(rows: Sequence[Mapping[str, Any]], path: tuple[str, ...] = ()):
    for row in rows:
        current = path + (row["name"],)
        if not row.get("section"):
            yield row, current
        yield from nodes(row.get("account_transactions", []), current)


def qualified(sheet: str, cell: str) -> str:
    return "'" + sheet.replace("'", "''") + "'!" + cell


def section(report: Mapping[str, Any], kind: str, path: Sequence[str]) -> Decimal:
    matches = [node for node, current in nodes(report[KEYS[kind]]) if current == tuple(path)]
    if len(matches) != 1:
        raise ValueError(f"Missing or ambiguous schedule section: {' / '.join(path)}")
    return amount(matches[0]["total"])


@dataclass(frozen=True)
class AssetVerification:
    asset_id: str
    name: str
    opening: Decimal
    before_cutoff: Decimal
    after_cutoff: Decimal
    purchase_date: str
    rate: Decimal
    fraction: Decimal
    calculated: Decimal
    posted: Decimal
    closing: Decimal
    difference: Decimal
    method: str
    location: str


@dataclass(frozen=True)
class SchedulePlan:
    values: dict[str, list[list[Any]]]
    note_total_rows: dict[int, int]
    asset_checks: dict[str, tuple[AssetVerification, ...]]
    warnings: tuple[str, ...]
    checks: dict[str, dict[str, str]]


def fetch_schedule_sources(books: Any, *, periods: Sequence[Mapping[str, str]],
                           excluded_location_id: str, include_opening_inventory: bool = False) -> dict[str, Any]:
    """Fetch each report once per year, then each in-scope asset and history once."""
    if len(periods) != 2:
        raise ValueError("Exactly two periods are required")
    reports = {}
    for p in periods:
        opening_date = (date.fromisoformat(p["start"]) - timedelta(days=1)).isoformat()
        needs_opening = include_opening_inventory and not any(q["end"] == opening_date for q in periods)
        reports[p["label"]] = fetch_schedule_reports(
            books, from_date=p["start"], to_date=p["end"], excluded_location_id=excluded_location_id,
            **({"include_opening_balance_sheet": True} if needs_opening else {}))
    assets = []
    seen = set()
    for asset in books.fixed_assets.list_iter(params={"filter_by": "Status.All"}, resource_key="fixedassets"):
        asset_id = str(asset.get("fixed_asset_id") or "")
        location = str(asset.get("location_id") or asset.get("branch_id") or "")
        if not location:
            raise ValueError(f"Asset has no location: {asset_id}")
        if location == excluded_location_id:
            continue
        if not asset_id or asset_id in seen:
            raise ValueError("Missing or duplicate fixed asset ID")
        seen.add(asset_id)
        if date.fromisoformat(asset["asset_purchase_date"]) > max(date.fromisoformat(p["end"]) for p in periods):
            continue
        detail = books.fixed_assets.get(asset_id)
        if detail.get("code") != 0 or not isinstance(detail.get("fixed_asset"), dict):
            raise ValueError(f"Missing fixed asset details: {asset_id}")
        assets.append({"asset": detail["fixed_asset"], "history": books.fixed_assets.history(asset_id)})
    result = {"reports": reports, "assets": assets, "excluded_location_id": excluded_location_id,
              "organization_id": str(books.organization_id), "periods": list(periods),
              "captured_at": datetime.now(timezone.utc).isoformat()}
    validate_sources(result, periods=periods, excluded_location_id=excluded_location_id)
    return result


def _validate_report(report: Mapping[str, Any], kind: str, *, start: str, end: str,
                     excluded_location_id: str) -> None:
    context = report.get("page_context", {})
    if (report.get("code") != 0 or not isinstance(report.get(KEYS[kind]), list)
            or context.get("to_date") != end
            or (kind == "profitandloss" and context.get("from_date") != start)
            or context.get("cash_based") != "false"
            or context.get("filter_by") != "TransactionDate.CustomDate"):
        raise ValueError("Schedule dates, basis or response shape do not match")
    rule = context.get("rule", {})
    columns = rule.get("columns", [])
    if (rule.get("criteria_string") != "1" or len(columns) != 1
            or any(columns[0].get(key) != value for key, value in {
                "field": "location_name", "value": [excluded_location_id],
                "comparator": "not_in", "group": "branch", "index": 1}.items())):
        raise ValueError("Schedule did not apply the configured branch exclusion")


def validate_sources(sources: Mapping[str, Any], *, periods: Sequence[Mapping[str, str]],
                     excluded_location_id: str) -> None:
    if len(periods) != 2 or sources.get("periods") != list(periods) or sources.get("excluded_location_id") != excluded_location_id:
        raise ValueError("Snapshot dates or excluded location do not match configuration")
    for p in periods:
        start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if start > end:
            raise ValueError("Invalid financial period")
        for kind in KEYS:
            report = sources["reports"][p["label"]][kind]
            _validate_report(report, kind, start=p["start"], end=p["end"],
                             excluded_location_id=excluded_location_id)
    seen = set()
    for item in sources["assets"]:
        asset = item["asset"]
        identity = asset["fixed_asset_id"]
        location = asset.get("location_id") or asset.get("branch_id")
        if not location or location == excluded_location_id or identity in seen:
            raise ValueError("Invalid asset location or duplicate asset")
        seen.add(identity)


def _opening_inventory(sources: Mapping[str, Any], config: Mapping[str, Any],
                      period: Mapping[str, str], note_number: int) -> Decimal:
    """Use prior closing stock with identical account overrides and verified scope."""
    opening_date = (date.fromisoformat(period["start"]) - timedelta(days=1)).isoformat()
    prior = next((p for p in config["periods"] if p["end"] == opening_date), None)
    report = (sources["reports"][prior["label"]]["balancesheet"] if prior else
              sources["reports"][period["label"]].get("balancesheet-opening"))
    if report is None:
        raise ValueError(f"Missing opening inventory balance sheet at {opening_date}")
    _validate_report(report, "balancesheet", start=opening_date, end=opening_date,
                     excluded_location_id=config["excluded_location_id"])
    seen = set()
    total = Decimal(0)
    for node, path in nodes(report[KEYS["balancesheet"]]):
        account = str(node.get("account_id") or "")
        if not account:
            continue
        if account in seen:
            raise ValueError(f"Duplicate opening inventory account: {account}")
        seen.add(account)
        override = config.get("account_notes", {}).get(account)
        candidates = [n for n in config["notes"] if n["report"] == "balancesheet" and
                      (n["number"] == override if override is not None else
                       any(path[:len(p)] == tuple(p) for p in n["paths"]))]
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous opening inventory classification: {node['name']}")
        if candidates and candidates[0]["number"] == note_number:
            total += amount(node["total"])
    return total


def verify_asset(asset: Mapping[str, Any], history: Sequence[Mapping[str, Any]], *,
                 start: str, end: str) -> AssetVerification:
    """Recalculate yearly declining depreciation from historical posted opening WDV.

    The acquisition day is included for prorata_basis, matching observed Books
    annual valuations. Unknown valuation types and unsupported methods fail.
    Today's asset value is never used as a historical year-end value.
    """
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    purchase = date.fromisoformat(asset["asset_purchase_date"])
    dep_start = date.fromisoformat(asset["depreciation_start_date"])
    if first > last:
        raise ValueError("Invalid asset verification period")
    if asset["depreciation_method"] != "declining_method" or asset["depreciation_frequency"] != "yearly":
        raise ValueError(f"Unsupported depreciation method/frequency: {asset['asset_name']}")
    computation = asset["computation_type"]
    if computation not in {"prorata_basis", "no_prorata"}:
        raise ValueError("Unsupported depreciation computation")
    rate = amount(asset["depreciation_percentage"]) / 100
    if not 0 <= rate <= 1:
        raise ValueError("Depreciation rate must be between 0 and 100")
    salvage = amount(asset["salvage_value"])
    if salvage != 0:
        raise ValueError("Non-zero salvage value needs a reviewed depreciation rule")
    events = []
    seen = set()
    for entry in history:
        identity = str(entry.get("valuation_id") or "")
        if not identity or identity in seen:
            raise ValueError("Missing or duplicate asset valuation")
        seen.add(identity)
        day = date.fromisoformat(entry["valuation_date"])
        if day > last:
            continue
        kind = entry["type"]
        if kind not in {"acquisition", "depreciation"}:
            raise ValueError(f"Unsupported asset event {kind}: {asset['asset_name']}")
        if kind == "acquisition" or entry.get("is_journal_posted") is True:
            events.append((day, entry))
    events.sort(key=lambda item: (item[0], item[1]["type"] != "acquisition"))
    acquisitions = [entry for _, entry in events if entry["type"] == "acquisition"]
    if purchase <= last and len(acquisitions) != 1:
        raise ValueError(f"Incomplete acquisition history: {asset['asset_name']}")
    value = Decimal(0)
    opening = Decimal(0)
    additions = Decimal(0)
    posted = Decimal(0)
    for day, entry in events:
        delta = amount(entry["revise_value"])
        if day < first:
            value += delta
            opening = value
        else:
            if entry["type"] == "acquisition":
                additions += delta
            else:
                posted += amount(entry["depreciated_value"])
            value += delta
        if abs(value - amount(entry["current_value"])) > Decimal("0.01"):
            raise ValueError(f"Asset history does not reconcile: {asset['asset_name']}")
    fraction = Decimal(0)
    active_start = max(first, dep_start)
    if active_start <= last:
        fraction = (Decimal((last - active_start).days + 1) / Decimal((last - first).days + 1)
                    if computation == "prorata_basis" else Decimal(1))
    calculated = money((opening + additions) * rate * fraction)
    cutoff = date(first.year, 9, 30)
    return AssetVerification(
        str(asset["fixed_asset_id"]), str(asset["asset_name"]), opening,
        additions if purchase <= cutoff else Decimal(0),
        additions if purchase > cutoff else Decimal(0), purchase.isoformat(),
        rate, fraction, calculated, posted, value, money(calculated - posted),
        computation, str(asset.get("location_name", "")),
    )


def build_schedule_plan(sources: Mapping[str, Any], config: Mapping[str, Any]) -> SchedulePlan:
    """Build two-year notes and statement links, with current-year assets only."""
    periods = config["periods"]
    validate_sources(sources, periods=periods, excluded_location_id=config["excluded_location_id"])
    labels = [p["label"] for p in periods]
    if len(set(labels)) != 2 or len(set(config["sheets"].values())) != 4:
        raise ValueError("Periods and managed sheet titles must be distinct")
    for period in periods:
        start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        if start != date(start.year, 4, 1) or end != date(start.year + 1, 3, 31):
            raise ValueError("Asset verification requires complete April–March financial years")
    notes = config["notes"]
    note_ids = [n["number"] for n in notes]
    if len(set(note_ids)) != len(note_ids):
        raise ValueError("Duplicate note number")
    targets = [(note["statement"], note["statement_row"]) for note in notes]
    targets += [(direct["statement"], direct["row"]) for direct in config["direct_inputs"]]
    if len(set(targets)) != len(targets):
        raise ValueError("Duplicate statement destination row")
    classified: dict[int, dict[str, dict[str, Any]]] = {n: {} for n in note_ids}
    warnings = []
    totals: dict[str, dict[int, Decimal]] = {label: {n: Decimal(0) for n in note_ids} for label in labels}
    for label in labels:
        for kind in KEYS:
            report = sources["reports"][label][kind]
            seen = set()
            for node, path in nodes(report[KEYS[kind]]):
                account = str(node.get("account_id") or "")
                is_earnings = path in [tuple(p) for p in config.get("standalone_paths", [])]
                if not account and not is_earnings:
                    continue
                identity = account or "/".join(path)
                if identity in seen:
                    raise ValueError(f"Duplicate schedule account: {identity}")
                seen.add(identity)
                value = amount(node["total"])
                override = config.get("account_notes", {}).get(account)
                candidates = ([n for n in notes if n["number"] == override and n["report"] == kind]
                              if override is not None else [n for n in notes if n["report"] == kind
                              and any(path[:len(p)] == tuple(p) for p in n["paths"])])
                if not candidates:
                    # Direct statement section inputs account for these sections.
                    allowed = any(d["report"] == kind and path[:len(d["path"])] == tuple(d["path"])
                                  for d in config["direct_inputs"])
                    if value and not allowed:
                        raise ValueError(f"Unclassified nonzero account: {node['name']}")
                    continue
                if len(candidates) != 1:
                    raise ValueError(f"Ambiguous note classification: {node['name']}")
                number = candidates[0]["number"]
                item = classified[number].setdefault(identity, {"name": node["name"], "amounts": {}})
                item["amounts"][label] = value
                totals[label][number] += value
    rollforward = config.get("inventory_rollforward")
    inventory_checks = {}
    if rollforward:
        purchases_note = rollforward["purchases_note"]
        inventory_note = rollforward["inventory_note"]
        purchase_config = next((n for n in notes if n["number"] == purchases_note), None)
        inventory_config = next((n for n in notes if n["number"] == inventory_note), None)
        changes = [d for d in config["direct_inputs"] if d.get("inventory_changes")]
        if (purchase_config is None or inventory_config is None
                or purchase_config["report"] != "profitandloss" or inventory_config["report"] != "balancesheet"
                or len(changes) != 1 or changes[0]["report"] != "profitandloss"
                or changes[0]["statement"] != purchase_config["statement"]
                or not changes[0].get("expense") or purchases_note not in config["checks"]["expense_notes"]):
            raise ValueError("Invalid inventory rollforward configuration")
        for period in periods:
            label = period["label"]
            if section(sources["reports"][label]["profitandloss"], "profitandloss", changes[0]["path"]):
                raise ValueError("Source inventory changes must be zero when purchases source represents COGS")
            opening = _opening_inventory(sources, config, period, inventory_note)
            closing = totals[label][inventory_note]
            cogs = totals[label][purchases_note]
            purchases = cogs - opening + closing
            inventory_checks[label] = {"cogs": cogs, "opening_stock": opening, "closing_stock": closing,
                                       "net_purchases": purchases, "changes_in_inventories": cogs - purchases}
            totals[label][purchases_note] = purchases
    note_sheet = config["sheets"]["notes"]
    rows: list[list[Any]] = [[config["company"]], ["Notes forming part of the Financial Statements"],
                            ["Particulars", periods[0]["end"], periods[1]["end"]]]
    total_rows = {}
    header_rows = {}
    cogs_row = None
    for note in notes:
        number = note["number"]
        header_rows[number] = len(rows) + 1
        rows.append([f"Note {number}: {note['title']}"])
        first_row = len(rows) + 1
        items = sorted(classified[number].items(), key=lambda pair: (pair[1]["name"].casefold(), pair[0]))
        if "groups" in note:
            groups = note["groups"]
            names = [group["name"] for group in groups]
            members = [str(account) for group in groups for account in group["account_ids"]]
            if not groups or any(not name for name in names) or len(set(names)) != len(names):
                raise ValueError(f"Invalid group names in Note {number}")
            if any(not group["account_ids"] for group in groups) or len(set(members)) != len(members):
                raise ValueError(f"Empty or duplicate group membership in Note {number}")
            ungrouped = [item["name"] for identity, item in items if identity not in members
                         and any(item["amounts"].values())]
            if ungrouped:
                raise ValueError(f"Ungrouped nonzero accounts in Note {number}: {', '.join(ungrouped)}")
            for group in groups:
                amounts = [sum((classified[number].get(str(account), {}).get("amounts", {}).get(label, Decimal(0))
                                for account in group["account_ids"]), Decimal(0)) for label in labels]
                rows.append([group["name"], *[float(money(value)) for value in amounts]])
            items = []
        for identity, item in items:
            amounts = [item["amounts"].get(label, Decimal(0)) for label in labels]
            if not any(amounts):
                continue
            rows.append([item["name"], *[float(money(v)) for v in amounts]])
        last_row = len(rows)
        total_rows[number] = len(rows) + 1
        rows.append(["Total", *[(f"=SUM({col}{first_row})" if first_row == last_row
                                 else f"=SUM({col}{first_row}:{col}{last_row})") if last_row >= first_row else "=0"
                                for col in ("B", "C")]])
        if rollforward and number == rollforward["purchases_note"]:
            cogs_row = len(rows)
            rows[-1][0] = "Cost of goods sold (Books)"
            rows.append(["Opening inventory", *[float(money(inventory_checks[label]["opening_stock"])) for label in labels]])
            rows.append(["Closing inventory", *[float(money(inventory_checks[label]["closing_stock"])) for label in labels]])
            rows.append(["Net purchases", *[f"={col}{cogs_row}-{col}{cogs_row + 1}+{col}{cogs_row + 2}" for col in ("B", "C")]])
            total_rows[number] = len(rows)
        rows.append([])
    values = {qualified(note_sheet, f"A1:C{len(rows)}"): rows}
    for note in notes:
        number = note["number"]
        sheet = config["sheets"][note["statement"]]
        row = note["statement_row"]
        for col, source_col in (("C", "B"), ("D", "C")):
            values[qualified(sheet, f"{col}{row}")] = [["=" + qualified(note_sheet, f"{source_col}{total_rows[number]}")]]
        values[qualified(sheet, f"B{row}")] = [[f'=HYPERLINK("#gid={config["sheet_ids"]["notes"]}&range=A{header_rows[number]}", {number})']]
    for direct in config["direct_inputs"]:
        sheet = config["sheets"][direct["statement"]]
        for col, label in zip(("C", "D"), labels):
            if rollforward and direct.get("inventory_changes"):
                source_col = "B" if col == "C" else "C"
                value = "=" + qualified(note_sheet, f"{source_col}{cogs_row}") + f"-{col}{purchase_config['statement_row']}"
            else:
                value = float(money(section(sources["reports"][label][direct["report"]], direct["report"], direct["path"])))
            values[qualified(sheet, f"{col}{direct['row']}")] = [[value]]
    checks = {}
    for label in labels:
        report = sources["reports"][label]
        assets = sum((totals[label][n] for n in config["checks"]["asset_notes"]), Decimal(0))
        liabilities = sum((totals[label][n] for n in config["checks"]["liability_notes"]), Decimal(0))
        # Include direct balance-sheet lines (borrowings/provisions).
        for direct in config["direct_inputs"]:
            if direct["report"] == "balancesheet":
                liabilities += section(report["balancesheet"], "balancesheet", direct["path"])
        revenue = sum((totals[label][n] for n in config["checks"]["revenue_notes"]), Decimal(0))
        expense = sum((totals[label][n] for n in config["checks"]["expense_notes"]), Decimal(0))
        for direct in config["direct_inputs"]:
            if direct.get("expense"):
                expense += (inventory_checks[label]["changes_in_inventories"] if rollforward and direct.get("inventory_changes")
                            else section(report["profitandloss"], "profitandloss", direct["path"]))
        expected_assets = section(report["balancesheet"], "balancesheet", ["ASSETS"])
        expected_liabilities = section(report["balancesheet"], "balancesheet", ["EQUITY AND LIABILITIES"])
        expected_pbt = section(report["profitandloss"], "profitandloss", config["checks"]["profit_before_tax_path"])
        pbt = revenue - expense - sum((section(report["profitandloss"], "profitandloss", d["path"])
                                      for d in config["direct_inputs"] if d.get("exceptional")), Decimal(0))
        for actual, expected, description in ((assets, expected_assets, "assets"),
                                              (liabilities, expected_liabilities, "liabilities"),
                                              (assets, liabilities, "balance sheet"), (pbt, expected_pbt, "profit before tax")):
            if abs(actual - expected) > Decimal("0.05"):
                raise ValueError(f"{label} {description} does not reconcile: {actual} versus {expected}")
        checks[label] = {"assets": str(money(assets)), "liabilities": str(money(liabilities)),
                         "profit_before_tax": str(money(pbt))}
        checks[label].update({key: str(money(value)) for key, value in inventory_checks.get(label, {}).items()})
        warnings.append(f"{label}: Books branch-rule echo verifies requested scope; SBE-named accounts can retain balances.")
    asset_checks = {}
    asset_rows: list[list[Any]] = []
    # Select by date so configuration ordering cannot switch depreciation years.
    for period in [max(periods, key=lambda p: date.fromisoformat(p["end"]))]:
        asset_rows.append([f"Assets & Depreciation — {period['label']}"])
        results = []
        accounts: dict[str, tuple[str, Decimal]] = {}
        asset_accounts: dict[str, str] = {}
        for item in sources["assets"]:
            asset = item["asset"]
            if asset.get("status") in {"draft", "cancel"}:
                warnings.append(f"Excluded unposted asset: {asset['asset_name']}")
                continue
            if asset["asset_purchase_date"] > period["end"]:
                continue
            result = verify_asset(asset, item["history"], start=period["start"], end=period["end"])
            reclass = None if config.get("asset_opening_source") == "ledger" else config.get("asset_opening_reclassifications", {}).get(result.asset_id)
            if reclass is not None:
                opening = amount(reclass)
                if result.opening or opening < 0 or opening > result.before_cutoff or result.purchase_date != period["start"]:
                    raise ValueError(f"Invalid opening reclassification: {result.name}")
                result = replace(result, opening=opening, before_cutoff=result.before_cutoff - opening)
            results.append(result)
            ledger_override = config.get("asset_ledger_overrides", {}).get(result.asset_id)
            ledger = ledger_override if ledger_override is not None else {"account_id": asset.get("asset_account_id"), "account_name": asset.get("asset_account_name")}
            account_id = str(ledger.get("account_id") or "")
            account_name = str(ledger.get("account_name") or "")
            if not account_id or not account_name:
                raise ValueError(f"Missing ledger account for asset: {result.name}")
            prior_name, opening = accounts.get(account_id, (account_name, Decimal(0)))
            if prior_name != account_name:
                raise ValueError(f"Inconsistent ledger account name: {account_id}")
            accounts[account_id] = (account_name, opening + result.opening)
            asset_accounts[result.asset_id] = account_id
            if abs(result.difference) > Decimal("0.01"):
                warnings.append(f"{period['label']} {result.name}: calculated minus posted depreciation {result.difference}")
        ledger_only = {}
        prior_period = next((p for p in periods if p["end"] == (date.fromisoformat(period["start"]) - timedelta(days=1)).isoformat()), None)
        ledger_entries = list(config.get("ledger_only_assets", []))
        if config.get("asset_opening_source") == "ledger":
            if prior_period is None:
                raise ValueError("Ledger asset opening requires the preceding year-end report")
            prior_report = sources["reports"][prior_period["label"]]["balancesheet"]
            ledger_accounts = {str(n["account_id"]): n for n, path in nodes(prior_report[KEYS["balancesheet"]])
                               if n.get("account_id") and "a. Fixed Assets" in path}
            dep_map = config.get("asset_accumulated_depreciation_accounts", {})
            depreciation_ids = [str(a) for ids in dep_map.values() for a in ids]
            if len(depreciation_ids) != len(set(depreciation_ids)):
                raise ValueError("Opening accumulated depreciation cannot be assigned twice")
            adjusted = []
            for account_id, (name, _) in list(accounts.items()):
                if account_id not in ledger_accounts:
                    raise ValueError(f"Missing opening fixed-asset ledger: {name}")
                opening = amount(ledger_accounts[account_id]["total"])
                for dep_id in dep_map.get(account_id, []):
                    if str(dep_id) not in ledger_accounts:
                        raise ValueError(f"Missing opening accumulated depreciation: {dep_id}")
                    opening += amount(ledger_accounts[str(dep_id)]["total"])
                members = [r for r in results if asset_accounts[r.asset_id] == account_id]
                eligible = [r for r in members if r.purchase_date <= period["start"]]
                if opening < 0 or (len(eligible) != 1 and sum((r.opening for r in members), Decimal(0)) != opening):
                    raise ValueError(f"Opening ledger balance needs reviewed asset allocation: {name}")
                for result in members:
                    target = opening if len(eligible) == 1 and result == eligible[0] else result.opening
                    delta = target - result.opening
                    if delta:
                        if result.purchase_date != period["start"] or delta > result.before_cutoff:
                            raise ValueError(f"Opening ledger/register basis differs: {result.name}")
                        result = replace(result, opening=target, before_cutoff=result.before_cutoff - delta)
                    adjusted.append(result)
                accounts[account_id] = (name, opening)
            results = adjusted
            for account_id, node in ledger_accounts.items():
                if account_id in accounts or account_id in depreciation_ids:
                    continue
                if node["name"].startswith("Accumulated Depreciation"):
                    if amount(node["total"]):
                        raise ValueError(f"Unassigned opening accumulated depreciation: {node['name']}")
                    continue
                if amount(node["total"]) and not any(str(e["account_id"]) == account_id for e in ledger_entries):
                    ledger_entries.append({"name": node["name"], "account_id": account_id, "account_name": node["name"]})
        for entry in ledger_entries:
            account_id = str(entry["account_id"])
            if account_id in accounts or account_id in ledger_only or prior_period is None:
                raise ValueError("Ledger-only asset overlaps the register or lacks prior year")
            balances = []
            for label in (prior_period["label"], period["label"]):
                matches = [n for n, path in nodes(sources["reports"][label]["balancesheet"][KEYS["balancesheet"]])
                           if str(n.get("account_id")) == account_id and "a. Fixed Assets" in path]
                if len(matches) != 1:
                    raise ValueError(f"Missing ledger-only fixed asset: {entry['name']}")
                balances.append(amount(matches[0]["total"]))
            ledger_only[account_id] = (entry["name"], balances[0], balances[1])
            accounts[account_id] = (entry["account_name"], balances[0])
            warnings.append(f"{period['label']} {entry['name']}: ledger-only asset; depreciation rate/history absent from register, no depreciation inferred.")
        asset_rows.extend([[f"Table 1: Asset opening balances — {period['start']}"],
                           ["Asset name", "Ledger account", "Opening WDV"]])
        ledger_subtotals = {}
        detail_rows = {}
        ordered_accounts = sorted(accounts.items(), key=lambda pair: (pair[1][0].casefold(), pair[0]))
        for account_id, (name, _) in ordered_accounts:
            first = len(asset_rows) + 1
            members = sorted((r for r in results if asset_accounts[r.asset_id] == account_id),
                             key=lambda r: (r.name.casefold(), r.asset_id))
            for result in members:
                detail_rows[result.asset_id] = len(asset_rows) + 1
                asset_rows.append([result.name, name, float(result.opening)])
            if account_id in ledger_only:
                asset_name, opening, _ = ledger_only[account_id]
                asset_rows.append([asset_name, name, float(opening)])
            last = len(asset_rows)
            ledger_subtotals[account_id] = len(asset_rows) + 1
            asset_rows.append(["Subtotal", name, f"=SUM(C{first}:C{last})" if last > first else f"=SUM(C{first})"])
        subtotal_refs = [f"C{row}" for row in ledger_subtotals.values()]
        asset_rows.extend([["Total", "", "=SUM(" + ",".join(subtotal_refs) + ")" if subtotal_refs else "=0"], [],
                           [f"Table 2: Depreciation and closing balances — {period['label']}"],
                           ["Ledger account", "Opening WDV", "Additions through 30 Sep", "Additions after 30 Sep",
                            "Total WDV before depreciation", "Depreciation expense", "Closing WDV",
                            "Calculated depreciation", "Expense minus calculated", "Books closing WDV", "WDV difference", "Rate"]])
        first_row = len(asset_rows) + 1
        days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
        for account_id, (name, _) in ordered_accounts:
            members = [result for result in results if asset_accounts[result.asset_id] == account_id]
            r = len(asset_rows) + 1
            if account_id in ledger_only:
                _, _, ledger_closing = ledger_only[account_id]
                asset_rows.append([name, f"=C{ledger_subtotals[account_id]}", "", "", f"=B{r}", "", float(ledger_closing),
                                   "", "", float(ledger_closing), f"=G{r}-J{r}", "Not in register"])
                continue
            terms = []
            for result in members:
                # Round per asset before summing; a ledger can have mixed dates/rates.
                active_days = int((result.fraction * days).to_integral_value())
                factor = "1" if active_days == days else f"{active_days}/{days}"
                additions = result.before_cutoff + result.after_cutoff
                additions_literal = str(int(additions)) if additions == additions.to_integral_value() else str(additions)
                terms.append(f"ROUND((C{detail_rows[result.asset_id]}+{additions_literal})*{result.rate}*{factor},2)")
            rates = {result.rate for result in members}
            asset_rows.append([name, f"=C{ledger_subtotals[account_id]}",
                               float(sum((m.before_cutoff for m in members), Decimal(0))),
                               float(sum((m.after_cutoff for m in members), Decimal(0))), f"=SUM(B{r}:D{r})",
                               float(sum((m.posted for m in members), Decimal(0))), f"=E{r}-F{r}",
                               "=SUM(" + ",".join(terms) + ")", f"=F{r}-H{r}",
                               float(sum((m.closing for m in members), Decimal(0))), f"=G{r}-J{r}",
                               float(next(iter(rates))) if len(rates) == 1 else "Mixed rates"])
        asset_checks[period["label"]] = tuple(results)
        last_row = len(asset_rows)
        total = ["Total"] + [""] * 11
        for col in "BCDEFGHIJK":
            total[ord(col) - ord("A")] = f"=SUM({col}{first_row}:{col}{last_row})" if last_row >= first_row else "=0"
        total_row = len(asset_rows) + 1
        dep_inputs = [d for d in config["direct_inputs"] if d["report"] == "profitandloss" and
                      d["path"] == config["checks"]["depreciation_path"]]
        if len(dep_inputs) != 1:
            raise ValueError("A unique P&L depreciation destination is required")
        pnl_column = "C" if period["label"] == labels[0] else "D"
        pnl_link = "=" + qualified(config["sheets"][dep_inputs[0]["statement"]], f"{pnl_column}{dep_inputs[0]['row']}")
        asset_rows.extend([total, ["P&L depreciation expense", "", "", "", "", pnl_link],
                           ["Difference vs P&L", "", "", "", "", f"=ROUND(F{total_row}-F{total_row + 1},2)"], []])
        posted = sum((r.posted for r in results), Decimal(0))
        pnl_depreciation = section(sources["reports"][period["label"]]["profitandloss"], "profitandloss",
                                   config["checks"]["depreciation_path"])
        checks[period["label"]]["registered_asset_depreciation"] = str(money(posted))
        checks[period["label"]]["pnl_depreciation"] = str(money(pnl_depreciation))
        if abs(posted - pnl_depreciation) > Decimal("0.01"):
            warnings.append(f"{period['label']}: fixed asset register posted depreciation {posted} versus P&L {pnl_depreciation}; ledger assets/journals need review.")
        register_wdv = sum((r.closing for r in results), Decimal(0))
        ledger_wdv = totals[period["label"]][6]
        checks[period["label"]]["registered_asset_wdv"] = str(money(register_wdv))
        checks[period["label"]]["fixed_asset_ledger_wdv"] = str(money(ledger_wdv))
        if abs(register_wdv - ledger_wdv) > Decimal("0.01"):
            warnings.append(f"{period['label']}: asset register closing WDV {register_wdv} versus Note 6 ledger WDV {ledger_wdv}; register coverage or ledger values need review.")
    values[qualified(config["sheets"]["assets"], f"A1:O{len(asset_rows)}")] = asset_rows
    return SchedulePlan(values, total_rows, asset_checks, tuple(warnings), checks)
