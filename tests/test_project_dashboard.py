import sys
import time
from pathlib import Path

import pytest

from apps import open_homepage
from apps.dashboard import WorkflowRunner, WorkflowSpec


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


def test_payment_preview_uses_production_review_refresh():
    runner = WorkflowRunner()

    preview = next(
        workflow for workflow in runner.list_workflows() if workflow["number"] == 2
    )

    assert preview["name"] == "Payment reconciliation preview"
    assert "payment_review.py --refresh-only" in preview["command"]


def test_homepage_launcher_reuses_running_dashboard(monkeypatch):
    opened = []
    monkeypatch.setattr(open_homepage, "dashboard_is_running", lambda: True)
    monkeypatch.setattr(
        open_homepage,
        "start_dashboard",
        lambda: pytest.fail("an existing dashboard should be reused"),
    )
    monkeypatch.setattr(open_homepage.webbrowser, "open", opened.append)

    assert open_homepage.main([]) == 0
    assert opened == [open_homepage.DASHBOARD_URL]


def test_homepage_launcher_starts_and_waits_for_dashboard(monkeypatch):
    health_checks = iter((False, False, True))

    class Process:
        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(
        open_homepage, "dashboard_is_running", lambda: next(health_checks)
    )
    monkeypatch.setattr(open_homepage, "start_dashboard", Process)
    monkeypatch.setattr(open_homepage.time, "sleep", lambda _seconds: None)

    assert open_homepage.main(["--no-browser"]) == 0
