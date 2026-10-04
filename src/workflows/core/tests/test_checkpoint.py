import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from workflows.core.checkpoint import atomic_text_writer, write_atomic_json


def test_atomic_json_writes_unicode_and_replaces_existing_file(tmp_path):
    target = tmp_path / "nested" / "checkpoint.json"
    write_atomic_json(target, {"old": True})
    write_atomic_json(target, {"text": "a → b"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "a → b"}
    assert list(target.parent.iterdir()) == [target]


def test_concurrent_writers_stage_independent_complete_payloads(tmp_path):
    target = tmp_path / "checkpoint.json"
    barrier = threading.Barrier(2)
    replace = os.replace
    staged_paths = []
    staging_lock = threading.Lock()

    def synchronized_replace(source, destination):
        with staging_lock:
            first_attempt = source not in staged_paths
            if first_attempt:
                staged_paths.append(source)
        if first_attempt:
            barrier.wait(timeout=5)
        replace(source, destination)

    payloads = [{"writer": 1, "data": "a" * 1000}, {"writer": 2, "data": "b" * 1000}]
    with patch("workflows.core.checkpoint.os.replace", side_effect=synchronized_replace):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write_atomic_json, target, payload) for payload in payloads]
            for future in futures:
                future.result(timeout=10)
    assert len(set(staged_paths)) == 2
    assert json.loads(target.read_text(encoding="utf-8")) in payloads
    assert list(tmp_path.iterdir()) == [target]


def test_replace_retries_permission_errors(tmp_path):
    target = tmp_path / "checkpoint.json"
    replace = os.replace
    attempts = 0

    def replace_after_unlock(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("locked")
        replace(source, destination)

    with patch("workflows.core.checkpoint.os.replace", side_effect=replace_after_unlock):
        with patch("workflows.core.checkpoint.time.sleep") as sleep:
            write_atomic_json(target, {"saved": True}, retry_delay=0.2)
    sleep.assert_called_once_with(0.2)
    assert json.loads(target.read_text()) == {"saved": True}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("error", [PermissionError("locked"), OSError("disk error")])
def test_failed_replace_preserves_target_and_cleans_staging(tmp_path, error):
    target = tmp_path / "checkpoint.json"
    target.write_text('{"old": true}', encoding="utf-8")
    with patch("workflows.core.checkpoint.os.replace", side_effect=error):
        with pytest.raises(type(error)):
            write_atomic_json(target, {"new": True}, max_retries=1)
    assert json.loads(target.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [target]


def test_serialization_failure_preserves_target_without_staging(tmp_path):
    target = tmp_path / "checkpoint.json"
    target.write_text('{"old": true}', encoding="utf-8")
    with pytest.raises(TypeError):
        write_atomic_json(target, {"invalid": object()}, default=None)
    assert json.loads(target.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [target]


def test_text_writer_failure_preserves_target_and_cleans_staging(tmp_path):
    target = tmp_path / "report.csv"
    target.write_text("previous", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed during formatting"):
        with atomic_text_writer(target, encoding="utf-8-sig", newline="") as handle:
            handle.write("partial")
            raise RuntimeError("failed during formatting")
    assert target.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [target]


def test_text_writer_retains_bom_and_json_retains_unicode_option(tmp_path):
    target = tmp_path / "report.csv"
    with atomic_text_writer(target, encoding="utf-8-sig", newline="") as handle:
        handle.write("name\r\nAcme\r\n")
    assert target.read_bytes() == b"\xef\xbb\xbfname\r\nAcme\r\n"
    target = tmp_path / "report.json"
    write_atomic_json(target, {"name": "→"}, indent=None, ensure_ascii=False, default=None)
    assert "→" in target.read_text(encoding="utf-8")
