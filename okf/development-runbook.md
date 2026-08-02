---
type: Runbook
title: Development Runbook
description: Local setup, validation commands, and safe development practices for the unified Zoho SDK and workflow packages.
tags: [development, testing, operations, workflows]
sources:
  - id: project-config
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/pyproject.toml
    title: Python project configuration
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# Local Setup

From the repository root, create and activate a virtual environment, then install the package with its test dependencies:

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

The shared `zoho_usable_functions` environment may also be used when it is available:

```powershell
& "d:/workplace/zoho_usable_functions/.venv/Scripts/pytest.exe" `
  "d:/workplace/zoho_sdk/tests" `
  "d:/workplace/zoho_sdk/src/zoho/workflows"
```

# Validation

Run the complete suite before publishing changes:

```powershell
python -m pytest
```

For environments without pytest, the low-level client suite can still be exercised directly:

```powershell
$env:PYTHONPATH = (Resolve-Path "src").Path
python -m unittest discover -s tests
```

Confirm both current and legacy imports after changes to public workflow exports:

```powershell
python -c "import zoho.workflows; import zoho_sdk_advanced"
```

# Development Rules

- Keep generic HTTP and service-client behavior below `zoho.workflows`.
- Inject low-level clients into workflows instead of importing workflow code from client packages.
- Mock network calls in unit tests. Live verification must use runtime credentials and read-only operations unless a mutation is explicitly intended.
- Never commit tokens, `.env` files, generated reports, logs, or `.codex` artifacts.
- Preserve the `zoho_sdk_advanced` compatibility surface when moving or renaming workflow exports.

# Safe Workflow Execution

Use dry-run options where a workflow provides them. Verify organization, domain, vendor, location, and destination identifiers before running mutations. Token values and authorization headers must never be logged.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [OKF Maintenance](okf-maintenance.md).
