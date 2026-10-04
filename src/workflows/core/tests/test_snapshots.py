import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from workflows.core import SnapshotPolicy, refresh_snapshot


NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def timestamp(value):
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def policy():
    return SnapshotPolicy(id_key="record_id", rows_key="rows", response_keys=("records", "alias"),
                          timestamp=timestamp, label="records", resource="records", require_source_timezone=True)


def refresh(path, api, loader, converter=None, selected_policy=None):
    return refresh_snapshot(api=api, snapshot_path=path, organization_id="org", workspace_id="workspace",
                            policy=selected_policy or policy(), analytics_loader=loader,
                            convert_baseline=converter or (lambda rows: rows), now=NOW)


def row(record_id, value):
    return {"record_id": record_id, "value": value, "last_modified_time": NOW.isoformat()}


def test_multi_page_overlay_alias_and_scoped_cache_reuse(tmp_path):
    path = tmp_path / "snapshot.json"
    baseline = [row("1", "old"), row("2", "unchanged")]
    loader = Mock(return_value=(baseline, NOW))
    api = Mock()
    api.list.side_effect = [
        {"records": [row("1", "new")], "page_context": {"has_more_page": True}},
        {"alias": [row("3", "added")], "page_context": {"has_more_page": False}}]
    result = refresh(path, api, loader)
    assert result == [row("1", "new"), row("2", "unchanged"), row("3", "added")]
    assert [call.kwargs["params"]["page"] for call in api.list.call_args_list] == [1, 2]
    saved = json.loads(path.read_text())
    assert saved["resource"] == "records"
    assert saved["organization_id"] == "org"
    assert saved["checked_at"] == NOW.isoformat()
    api.list.side_effect = None
    api.list.return_value = {"records": []}
    loader.reset_mock()
    assert refresh(path, api, loader) == result
    loader.assert_not_called()


@pytest.mark.parametrize("field, value", [("organization_id", "other"), ("workspace_id", "other"),
                                         ("resource", "other"), ("schema_version", 0)])
def test_snapshot_identity_mismatch_reloads_baseline(tmp_path, field, value):
    path = tmp_path / "snapshot.json"
    api = Mock()
    api.list.return_value = {"records": []}
    loader = Mock(return_value=([row("1", "old")], NOW))
    refresh(path, api, loader)
    saved = json.loads(path.read_text())
    saved[field] = value
    path.write_text(json.dumps(saved))
    loader.reset_mock()
    refresh(path, api, loader)
    loader.assert_called_once()


@pytest.mark.parametrize("source_at, message", [(NOW - timedelta(hours=25), "older than 24 hours"),
                                               (NOW.replace(tzinfo=None), "must include a timezone")])
def test_bad_baseline_time_fails_before_conversion_or_write(tmp_path, source_at, message):
    api = Mock()
    path = tmp_path / "snapshot.json"
    converter = Mock(side_effect=AssertionError("must not convert"))
    with pytest.raises(ValueError, match=message):
        refresh(path, api, Mock(return_value=([], source_at)), converter)
    converter.assert_not_called()
    api.list.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize("response", [
    {"records": None},
    {"records": [], "page_context": {"has_more_page": True}},
    {"records": [{"record_id": "1"}]},
    {"records": [{"record_id": "1", "last_modified_time": (NOW - timedelta(days=3)).isoformat()}]},
])
def test_invalid_or_incomplete_changes_preserve_good_snapshot(tmp_path, response):
    path = tmp_path / "snapshot.json"
    api = Mock()
    api.list.return_value = {"records": []}
    loader = Mock(return_value=([row("1", "good")], NOW))
    refresh(path, api, loader)
    original = path.read_bytes()
    api.list.return_value = response
    with pytest.raises(ValueError):
        refresh(path, api, loader)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
