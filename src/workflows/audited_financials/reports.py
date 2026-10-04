"""Configuration-driven, registration-specific read-only Books report helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from workflows.core.config import Config, get_config


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _firm_rule(firm: str | None, config_path: Path | None) -> dict[str, Any]:
    path = config_path or Path(get_config(
        "FIRM_REPORT_CONFIG", str(Path(Config.PROJECT_ROOT) / "config/firm-reports.yaml")))
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not isinstance(config.get("firms"), dict) or not config["firms"]:
        raise ValueError("Firm report configuration needs a non-empty firms mapping")
    aliases: dict[str, str] = {}
    rules: dict[str, dict[str, Any]] = {}
    for identifier, entry in config["firms"].items():
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(entry, dict):
            raise ValueError("Firm entries must be named objects")
        name, gstin = entry.get("name"), entry.get("gstin")
        extra = entry.get("aliases", [])
        scope = entry.get("scope")
        if (not isinstance(name, str) or not name.strip() or not isinstance(gstin, str) or not gstin.strip()
                or not isinstance(extra, list) or any(not isinstance(alias, str) or not alias.strip() for alias in extra)
                or not isinstance(scope, dict)):
            raise ValueError(f"Invalid name, GSTIN, aliases or scope for firm {identifier}")
        comparator, locations = scope.get("comparator"), scope.get("location_ids")
        if (comparator not in ("in", "not_in") or not isinstance(locations, list) or not locations
                or any(not isinstance(item, str) or not item.strip() or item != item.strip() for item in locations)
                or len(set(locations)) != len(locations)):
            raise ValueError(f"Invalid location scope for firm {identifier}")
        for alias in [identifier, name, gstin, *extra]:
            key = _normalize(alias)
            if key in aliases and aliases[key] != identifier:
                raise ValueError(f"Ambiguous firm alias: {alias}")
            aliases[key] = identifier
        rules[identifier] = {"columns": [{"index": 1, "field": "location_name",
            "value": locations, "comparator": comparator, "group": "branch"}], "criteria_string": "1"}
    selected = config.get("default_firm") if firm is None else firm
    key = _normalize(selected) if isinstance(selected, str) else ""
    if key not in aliases:
        raise ValueError("Unknown firm or reviewed GSTIN; check the firm report configuration")
    return rules[aliases[key]]


def fetch_trial_balance_for_firm(
    books_client: Any, *, from_date: str, to_date: str,
    firm: str | None = None, show_rows: str = "non_zero", config_path: Path | None = None,
) -> Mapping[str, Any]:
    """Fetch accrual trial balance using configured firm aliases and location scope.

    Omitted firm uses default_firm from YAML. Names, abbreviations and GSTINs
    are case insensitive and tolerate surrounding/repeated whitespace.
    """
    rule = json.dumps(_firm_rule(firm, config_path), separators=(",", ":"))
    return books_client.reports.trial_balance(
        from_date=from_date, to_date=to_date, rule=rule,
        cash_based=False, show_rows=show_rows,
    )


def fetch_trial_balance_for_gstin(
    books_client: Any, *, from_date: str, to_date: str,
    gstin: str | None = None, show_rows: str = "non_zero", config_path: Path | None = None,
) -> Mapping[str, Any]:
    """Compatibility wrapper accepting a configured GSTIN or firm alias."""
    return fetch_trial_balance_for_firm(
        books_client, from_date=from_date, to_date=to_date,
        firm=gstin, show_rows=show_rows, config_path=config_path,
    )
