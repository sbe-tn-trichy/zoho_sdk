"""Prepare configured note schedules and Sheets formulas without mutating Books."""
from __future__ import annotations

from dataclasses import dataclass
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
    """Build managed note blocks, statement links and two annual asset tables."""
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
    for period in periods:
        asset_rows.append([f"Assets & Depreciation — {period['label']}"])
        asset_rows.append(["PARTICULARS", "Opening WDV", "Additions through 30 Sep", "Additions after 30 Sep",
                           "Date of purchase", "TOTAL", "RATE", "Calculated depreciation", "Calculated closing WDV",
                           "Books posted depreciation", "Depreciation difference", "Books closing WDV", "WDV difference",
                           "Computation", "Location"])
        results = []
        first_row = len(asset_rows) + 1
        for item in sources["assets"]:
            asset = item["asset"]
            if asset.get("status") in {"draft", "cancel"}:
                warnings.append(f"Excluded unposted asset: {asset['asset_name']}")
                continue
            if asset["asset_purchase_date"] > period["end"]:
                continue
            result = verify_asset(asset, item["history"], start=period["start"], end=period["end"])
            results.append(result)
            r = len(asset_rows) + 1
            # Integer day ratios survive Sheets' decimal-literal normalization.
            days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1
            active_days = int((result.fraction * days).to_integral_value())
            factor = "1" if active_days == days else f"{active_days}/{days}"
            asset_rows.append([result.name, float(result.opening), float(result.before_cutoff), float(result.after_cutoff),
                               result.purchase_date, f"=SUM(B{r}:D{r})", float(result.rate),
                               f"=ROUND(F{r}*G{r}*{factor},2)", f"=F{r}-H{r}", float(result.posted),
                               f"=H{r}-J{r}", float(result.closing), f"=I{r}-L{r}", result.method, result.location])
            if abs(result.difference) > Decimal("0.01"):
                warnings.append(f"{period['label']} {result.name}: calculated minus posted depreciation {result.difference}")
        asset_checks[period["label"]] = tuple(results)
        last_row = len(asset_rows)
        total = ["Total"] + [""] * 14
        for col in ("B", "C", "D", "F", "H", "I", "J", "K", "L", "M"):
            total[ord(col) - ord("A")] = f"=SUM({col}{first_row}:{col}{last_row})" if last_row >= first_row else "=0"
        asset_rows.extend([total, []])
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
