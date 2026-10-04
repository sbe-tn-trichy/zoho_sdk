import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.books_account_catalog import (
    refresh_mapping_account_names,
    sync_account_catalog,
)


def test_sync_replaces_sqlite_snapshot_and_returns_names(tmp_path):
    chart = Mock()
    chart.list_all.side_effect = [[
        {
            "account_id": "a-1",
            "account_name": "Cash",
            "account_code": "100",
            "account_type": "cash",
            "parent_account_id": "",
            "is_active": True,
        },
    ], [
        {"account_id": "a-2", "account_name": "Sales", "is_active": False},
    ]]
    database = tmp_path / "accounts.sqlite3"

    names = sync_account_catalog(SimpleNamespace(chart_of_accounts=chart), database)

    assert names == {"a-1": "Cash", "a-2": "Sales"}
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT account_id, account_name, is_active FROM accounts ORDER BY account_id"
        ).fetchall()
    assert rows == [("a-1", "Cash", 1), ("a-2", "Sales", 0)]
    assert chart.list_all.call_args_list == [
        (( ), {"params": {"filter_by": "AccountType.Active"}}),
        (( ), {"params": {"filter_by": "AccountType.Inactive"}}),
    ]


def test_refresh_mapping_names_tracks_account_id_order():
    config = {"mappings": [{"account_ids": ["a-2", "a-1"], "account_names": ["Old"]}]}

    assert refresh_mapping_account_names(config, {"a-1": "Cash", "a-2": "Sales"})
    assert config["mappings"][0]["account_names"] == ["Sales", "Cash"]
    assert not refresh_mapping_account_names(config, {"a-1": "Cash", "a-2": "Sales"})


def test_refresh_mapping_names_rejects_unknown_account_id():
    config = {"mappings": [{"account_ids": ["missing"]}]}
    with pytest.raises(ValueError, match="unknown Books account IDs: missing"):
        refresh_mapping_account_names(config, {})


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_mapping_refresh_preserves_other_accounting_sections(tmp_path, suffix):
    import yaml
    from workflows.books_account_catalog import write_mapping_config
    path = tmp_path / ("mapping" + suffix)
    config = {"calculations": {"sales": {"accounts": {"Sales": 1}}},
              "mappings": [{"account_ids": ["a"], "account_names": ["Old"]}]}
    assert refresh_mapping_account_names(config, {"a": "Sales"})
    write_mapping_config(path, config)
    loaded = json.loads(path.read_text()) if suffix == ".json" else yaml.safe_load(path.read_text())
    assert loaded == config
    assert not list(tmp_path.glob("*.tmp"))
