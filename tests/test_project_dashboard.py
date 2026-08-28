import sys
import time
from pathlib import Path

import pytest

from scripts.project_dashboard import WorkflowRunner, WorkflowSpec


def test_runner_executes_allowlisted_workflow(tmp_path: Path):
    spec = WorkflowSpec(
        number=9,
        name="Test workflow",
        description="A small test command.",
        command=(sys.executable, "-c", "print('ready')"),
        category="Test",
    )
    runner = WorkflowRunner(repo_root=tmp_path, workflows=(spec,))

    started = runner.start(9)
    deadline = time.monotonic() + 5
    result = started
    while result["status"] in {"starting", "running"} and time.monotonic() < deadline:
        time.sleep(0.02)
        result = runner.get(started["run_id"])

    assert result["status"] == "succeeded"
    assert result["exit_code"] == 0
    assert result["logs"] == ["ready"]


def test_runner_rejects_unknown_number(tmp_path: Path):
    runner = WorkflowRunner(repo_root=tmp_path, workflows=())

    with pytest.raises(ValueError, match="Unknown workflow number"):
        runner.start(99)


def test_registry_exposes_only_safe_default_commands():
    runner = WorkflowRunner()

    commands = [item["command"] for item in runner.list_workflows()]

    assert commands
    assert all("--execute" not in command for command in commands)
    assert all("--allow-batch" not in command for command in commands)
