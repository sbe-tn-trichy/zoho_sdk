# Zoho SDK

Python 3.14 clients for Books, Inventory, Creator, Analytics, WorkDrive, Mail,
Cliq and Sheet, with reusable business workflows and local review applications.

## Start here

From the repository root, install into the workspace virtual environment:

```bash
uv venv --python 3.14
.venv/bin/python -m pip install -e ".[workflows,test]"
```

If your environment was created without pip, use
`uv pip install --python .venv/bin/python -e ".[workflows,test]"`.

Open the local operations dashboard:

```bash
.venv/bin/python apps/dashboard.py
```

Visit `http://127.0.0.1:8750` to browse common workflows and see their run output.
The dashboard uses safe defaults; review applications have their own explicit
mutation controls. For a specific command, start with its `--help` and the
linked operational documentation.

## Find the right place

| Need | Start here |
|---|---|
| Choose a business workflow | [Workflow catalog](WORKFLOWS.md) |
| Find SDK classes and methods | [SDK reference](INDEX.md) |
| Configure application clients and credentials | [Configuration](okf/configuration.md) |
| Understand imports and module boundaries | [Architecture](okf/architecture.md) |
| Understand overlapping entry points | [Project organization](okf/project-organization.md) |
| Develop and test | [Development runbook](okf/development-runbook.md) |
| Find detailed operating contracts | [Knowledge index](okf/index.md) |

## Code organization

```text
src/zoho/       API clients, transport, resources and generic API helpers
src/workflows/ Business rules; injected clients; no servers or CLI parsers
apps/          CLI commands and local review servers
apps/static/   Web HTML, CSS and JavaScript
tests/        SDK and application tests (workflow tests also live beside code)
scripts/       Temporary, ignored scratch work
output/        Generated reports and checkpoints, ignored by Git
```

Imports flow `zoho <- workflows <- apps`. Shared workflow mechanics live in
`workflows.core`; domain rules stay in their workflow packages. Inventory owns
item/catalog operations, including item lookups needed for Books transactions.

## Use the library

Low-level SDK constructors take credentials explicitly. Application runners load
configuration and construct clients through `workflows.core.auth`. Keep tokens
out of source code, reports and logs.

```python
from zoho import ZohoBooksAPI
from workflows import GSTR1VerificationConfig, verify_gstr1

books = ZohoBooksAPI(access_token=token, organization_id=org_id, domain="in")
report = verify_gstr1(
    books,
    config=GSTR1VerificationConfig(e_invoice_applicable=True),
)
```

See [GSTR-1 verification](okf/gstr1-verification.md) for report semantics and
[Analytics metadata](okf/analytics-metadata.md) for query and snapshot operations.
Workflow extras are optional when using only the low-level SDK.

## Validate changes

```bash
.venv/bin/pytest -q
```

Tests include `tests/` and workflow-local suites under `src/workflows/`.
[Repository guidance](AGENTS.md) defines development and documentation rules.
