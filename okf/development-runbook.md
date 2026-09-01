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
python -m pip install -e ".[workflows,test]"
```

The shared `zoho_usable_functions` environment may also be used when it is available:

```powershell
& "d:/workplace/zoho_usable_functions/.venv/Scripts/pytest.exe" `
  "d:/workplace/zoho_sdk/tests" `
  "d:/workplace/zoho_sdk/src/workflows"
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

Confirm the SDK and standalone workflow packages import successfully:

```powershell
python -c "import zoho; import workflows"
```

The package currently supports Python 3.8 and newer. Avoid runtime-evaluated
PEP 604 unions and built-in collection generics unless the module uses
postponed annotations; the validation matrix should include Python 3.8.

# Development Rules

- Keep generic HTTP and service-client behavior below `workflows`.
- Inject low-level clients into workflows instead of importing workflow code from client packages.
- Mock network calls in unit tests. Live verification must use runtime credentials and read-only operations unless a mutation is explicitly intended.
- Keep every concrete service `request()` override compatible with the full `BaseZohoClient.request()` signature and forward transport options unchanged.
- Treat `POST`, `PUT`, `PATCH`, and `DELETE` as mutations. Mark a semantically read-only POST explicitly with `is_mutation=False` and cover the exception with a test.
- Never commit tokens, `.env` files, generated reports, logs, or `.codex` artifacts.
- Use canonical `workflows` package names. Retain a compatibility alias only when
  it is explicit, documented, and covered by tests.
- All files placed in `scripts/` are strictly temporary with a 24-hour retention lifespan. Permanent user-facing tools, web servers, and CLI runners belong in `apps/`.
- Never inline HTML/CSS/JS in Python files; save web templates under `apps/static/`.
- Subclass `zoho.base_resource.BaseResource` for all Books and Inventory resources to prevent duplicate CRUD and pagination logic.
- Declare explicit type annotations (PEP 484) on all public function signatures instead of untyped `*args, **kwargs`.
- Use `workflows.core.auth` client factories for all SDK client instantiations.
- Save generated project artifacts under `output/` by default. A documented API
  may honor an explicit absolute caller path after safe validation.

# Safe Workflow Execution

Use dry-run options where a workflow provides them. Verify organization, domain, vendor, location, and destination identifiers before running mutations. Token values and authorization headers must never be logged.

## NeoSeal item alias review

Run the read-only export below to create an all-items catalog and a smaller
review list for NeoSeal Books items that do not yet have an `alias_name`:

```bash
PYTHONPATH=src .venv/bin/python apps/export_neoseal_items.py \
  --purchase-account-id "$NEOSEAL_PURCHASE_ACCOUNT_ID"
```

The default outputs are `output/neoseal_items.csv` and
`output/neoseal_items_missing_alias.csv`. The latter is the working list for
recording the vendor's exact supplied item name in Books `alias_name`; the
script scopes the catalog by the dedicated NeoSeal purchase account rather than
by a free-text manufacturer value, and never creates or updates Books items.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [OKF Maintenance](okf-maintenance.md).
