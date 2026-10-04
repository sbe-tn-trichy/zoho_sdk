"""Persist the Zoho Books chart of accounts and annotate statement mappings."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from workflows.core.checkpoint import atomic_text_writer, write_atomic_json


def sync_account_catalog(
    books: Any,
    database_path: Path,
    report_params: Mapping[str, Any] | None = None,
    reports: Sequence[str] = (),
) -> dict[str, str]:
    """Snapshot chart and report-only accounts, then return names by ID."""
    accounts = []
    for account_filter in ("AccountType.Active", "AccountType.Inactive"):
        accounts.extend(
            books.chart_of_accounts.list_all(params={"filter_by": account_filter})
        )
    report_roots = {
        "balancesheet": "balance_sheet",
        "profitandloss": "profit_and_loss",
    }

    def collect_report_accounts(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            if node.get("account_id") and node.get("name"):
                accounts.append({
                    "account_id": node["account_id"],
                    "account_name": node["name"],
                    "account_code": node.get("account_code", ""),
                    "account_type": "report_only",
                    "is_active": True,
                })
            collect_report_accounts(node.get("account_transactions"))

    for report in dict.fromkeys(reports):
        if report not in report_roots:
            raise ValueError(f"Unsupported account catalog report: {report}")
        response = books.request(
            "GET", f"reports/{report}", params=dict(report_params or {})
        )
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise ValueError(f"Books {report} failed while refreshing account catalog")
        collect_report_accounts(response.get(report_roots[report]))
    rows: list[tuple[str, str, str, str, str, int, str, str]] = []
    names: dict[str, str] = {}
    synced_at = datetime.now(timezone.utc).isoformat()
    for account in accounts:
        account_id = str(account.get("account_id") or "").strip()
        account_name = str(account.get("account_name") or account.get("name") or "").strip()
        if not account_id or not account_name:
            raise ValueError("Every Books account must have an account_id and account_name")
        if account_id in names:
            if names[account_id] == account_name:
                continue
            raise ValueError(f"Conflicting Books account name for ID: {account_id}")
        names[account_id] = account_name
        rows.append((
            account_id,
            account_name,
            str(account.get("account_code") or ""),
            str(account.get("account_type") or ""),
            str(account.get("parent_account_id") or ""),
            int(bool(account.get("is_active", True))),
            json.dumps(account, ensure_ascii=False, sort_keys=True),
            synced_at,
        ))
    if not rows:
        raise ValueError("Zoho Books returned an empty chart of accounts")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                account_name TEXT NOT NULL,
                account_code TEXT NOT NULL,
                account_type TEXT NOT NULL,
                parent_account_id TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                synced_at TEXT NOT NULL
            )
        """)
        connection.execute("DELETE FROM accounts")
        connection.executemany(
            """INSERT INTO accounts (
                account_id, account_name, account_code, account_type,
                parent_account_id, is_active, raw_json, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS accounts_name_idx ON accounts(account_name)"
        )
    return names


def refresh_mapping_account_names(
    config: MutableMapping[str, Any], account_names: Mapping[str, str]
) -> bool:
    """Refresh ordered account_names arrays for every account-ID mapping."""
    mappings = config.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("Mapping configuration must contain a mappings array")
    changed = False
    for mapping in mappings:
        if not isinstance(mapping, MutableMapping):
            raise ValueError("Every mapping must be an object")
        raw_ids = mapping.get("account_ids")
        if raw_ids is None:
            continue
        if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
            raise ValueError("account_ids must be an array")
        ids = [str(value).strip() for value in raw_ids]
        missing = [account_id for account_id in ids if account_id not in account_names]
        if missing:
            raise ValueError(
                "Mapping references unknown Books account IDs: " + ", ".join(missing)
            )
        refreshed = [account_names[account_id] for account_id in ids]
        if mapping.get("account_names") != refreshed:
            mapping["account_names"] = refreshed
            changed = True
    return changed


def write_mapping_config(path: Path, config: Mapping[str, Any]) -> None:
    """Atomically write refreshed mapping metadata."""
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        text = yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False)
        with atomic_text_writer(path) as staged:
            staged.write(text)
    else:
        write_atomic_json(path, config, ensure_ascii=False, default=None)
