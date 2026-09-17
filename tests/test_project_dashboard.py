import sys
import time
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from apps import open_homepage
from apps.dashboard import (
    WORKFLOWS,
    WorkflowRunner,
    WorkflowSpec,
    filter_dashboard_workflows,
)


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
    runnable_commands = [command for command in commands if command]
    assert all("--execute" not in command for command in runnable_commands)
    assert all("--allow-batch" not in command for command in runnable_commands)


def test_registry_catalogues_every_domain_workflow():
    workflows = WorkflowRunner().list_workflows()
    represented = {item["workflow"] for item in workflows}

    assert represented == {
        "collection_reconciliation",
        "creator_customer_sync",
        "duplicate_payment_check",
        "gstr1_verification",
        "neoseal_audit",
        "neoseal_stock_count",
        "polycab_credit_memos",
        "polycab_rso",
        "stock_transfer",
        "vendor_customer_offset",
        "vendor_ledger_reconciliation",
    }


def test_removed_icici_export_is_not_registered():
    runner = WorkflowRunner()

    assert all(item["number"] != 4 for item in runner.list_workflows())
    with pytest.raises(ValueError, match="Unknown workflow number"):
        runner.start(4)


def test_dashboard_workflow_config_includes_selected_domains():
    selected = filter_dashboard_workflows(
        WORKFLOWS,
        {"include": ["collection_reconciliation", "gstr1_verification"]},
    )

    assert {item.workflow for item in selected} == {
        "collection_reconciliation",
        "gstr1_verification",
    }


def test_dashboard_workflow_config_exclusion_takes_precedence():
    selected = filter_dashboard_workflows(
        WORKFLOWS,
        {
            "include": ["collection_reconciliation", "gstr1_verification"],
            "exclude": ["collection_reconciliation"],
        },
    )

    assert [item.workflow for item in selected] == ["gstr1_verification"]


def test_dashboard_workflow_config_rejects_unknown_ids():
    with pytest.raises(ValueError, match="unknown workflow IDs"):
        filter_dashboard_workflows(WORKFLOWS, {"exclude": ["typo"]})


def test_runner_explains_when_workflow_needs_setup():
    runner = WorkflowRunner()

    with pytest.raises(ValueError, match="Choose a return month"):
        runner.start(9)


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


def test_dashboard_tabs_favorites_and_search():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to exercise the dashboard JavaScript")

    html = (Path(__file__).resolve().parents[1] / "apps/static/dashboard.html").read_text()
    script = re.search(r"<script>(.*?)</script>", html, re.DOTALL).group(1)
    harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(0, 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', value: '', scrollLeft: 0,
    addEventListener() {}, contains() { return false; },
  });
  return elements.get(id);
}
const stored = new Map();
const context = {
  assert,
  document: {
    activeElement: null,
    querySelector() { return { content: 'test-token' }; },
    getElementById: element,
  },
  localStorage: {
    getItem(key) { return stored.get(key) || null; },
    setItem(key, value) { stored.set(key, value); },
  },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
};
vm.runInNewContext(source + `
  state = { workflows: [
    { number: 1, name: 'Payment reconciliation', description: 'Payments', category: 'Collections', workflow: 'collection_reconciliation', available: true, safety: 'Read-only' },
    { number: 2, name: 'Neoseal audit', description: 'Items', category: 'Inventory', workflow: 'neoseal_audit', available: true, safety: 'Read-only' }
  ], runs: [] };
  render();
  assert.match(document.getElementById('tabs').innerHTML, /Reconciliation/);
  assert.match(document.getElementById('tabs').innerHTML, /Inventory/);
  assert.match(document.getElementById('grid').innerHTML, /Payment reconciliation/);
  assert.match(document.getElementById('grid').innerHTML, /Neoseal audit/);
  activeTab = 'Reconciliation'; render();
  assert.match(document.getElementById('grid').innerHTML, /Payment reconciliation/);
  assert.doesNotMatch(document.getElementById('grid').innerHTML, /Neoseal audit/);
  toggleFavorite(2);
  assert.equal(localStorage.getItem(favoritesKey), '[2]');
  activeTab = 'Favorites'; render();
  assert.match(document.getElementById('grid').innerHTML, /Neoseal audit/);
  assert.doesNotMatch(document.getElementById('grid').innerHTML, /Payment reconciliation/);
  query = 'payment'; activeTab = 'All'; render();
  assert.match(document.getElementById('grid').innerHTML, /Payment reconciliation/);
  assert.doesNotMatch(document.getElementById('grid').innerHTML, /Neoseal audit/);
  query = ''; activeTab = 'Favorites'; toggleFavorite(2);
  assert.match(document.getElementById('grid').innerHTML, /No favorites yet/);
`, context);
const blockedStorage = {
  getItem() { throw new Error('storage blocked'); },
  setItem() { throw new Error('storage blocked'); },
};
vm.runInNewContext(source + `
  state = { workflows: [
    { number: 2, name: 'Neoseal audit', description: 'Items', category: 'Inventory', workflow: 'neoseal_audit', available: true, safety: 'Read-only' }
  ], runs: [] };
  toggleFavorite(2);
  activeTab = 'Favorites'; render();
  assert.match(document.getElementById('grid').innerHTML, /Neoseal audit/);
`, { ...context, localStorage: blockedStorage });
"""
    result = subprocess.run(
        [node, "-e", harness], input=script, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
