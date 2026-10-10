# Repository Guidance

## Source of Truth

- Code and tests are authoritative. Use [`INDEX.md`](INDEX.md) only as a
  navigation aid.
- Before a multi-file or behavior-changing task, read [`okf/index.md`](okf/index.md)
  and the relevant concepts. Correct stale concepts in the same change.

## Development Priorities

Apply these priorities in order; satisfying the requested outcome must preserve
correctness and data safety:

1. **Requested business outcome:** Deliver the task's required behavior. Avoid
   speculative features, frameworks, and unrelated cleanup.
2. **Correctness and data safety:** Preserve accounting rules, vendor scoping,
   explicit mutation intent, recovery checkpoints, and required live verification.
3. **Usability:** Make command selection, inputs, defaults, reports, and errors
   understandable. Explain what an operation will change.
4. **Readability:** Use focused functions, descriptive names, typed inputs, and
   business rules that are easy to locate. Comments explain reasons rather than
   repeat mechanics already clear from the code.
5. **Reuse and maintainability:** Share mechanics only when their semantics match.
   Keep distinct business rules separate even when their implementations resemble
   one another.
6. **Performance:** Optimize demonstrated bottlenecks, especially repeated API
   calls, without obscuring correctness.

## Task Scope and Acceptance

- Establish the expected outcome, acceptance criteria, and whether live changes
  are authorized from the user's request and session context. Ask only when
  material information or authorization is missing; routine work does not need
  a separate approval step.
- Complete the agreed scope before introducing adjacent improvements.
- Tie refactoring to a concrete usability, correctness, or maintenance problem.
  Preserve behavior unless a behavior change is requested or necessary for the
  authorized fix. File size alone is not a reason to rewrite a module.
- For project cleanup, prioritize clear workflow ownership and command selection
  before extracting specific duplicated logic.

## Architecture

- Library code lives in `src/zoho/` (low-level clients) and `src/workflows/`
  (domain workflows); permanent entry points live in `apps/`.
- Imports flow `zoho <- workflows <- apps`. Neither `zoho` nor `workflows` may
  import from `apps` or `scripts`; workflows contain no servers or CLI parsers.
- `scripts/` is Git-ignored scratch space with a retention target under 24 hours.
- Keep web HTML/CSS/JS in `apps/static/`, loaded from Python rather than embedded.
- Export supported public APIs and exceptions from the relevant `__init__.py`.

## Implementation

- Prefer small reusable modules and established dependencies over duplicate or
  bespoke infrastructure.
- Extend the existing owner first. Add a module when it has a distinct
  responsibility, and prefer small helpers with explicit inputs over generic
  engines with many switches.
- Compare business semantics before consolidating code; similar names or
  structure alone do not establish duplication.
- Give each operation a clear primary entry point. Retain older commands only
  for needed compatibility, documented and covered by tests.
- Fail with actionable context. Never silently skip invalid financial records
  or report incomplete work as successful.
- Books and Inventory resources reuse `zoho.base_resource.BaseResource`.
- Reuse `workflows.core.matching` conversions when their semantics fit.
- Public APIs use explicit typed parameters. Use `TypedDict` or dataclasses for
  stable structured records crossing workflow boundaries.
- Applications construct SDK clients through `workflows.core.auth` factories.
- Use the Zoho Inventory API for item and inventory-related operations, including
  item catalog reads and updates, stock, warehouses, and inventory adjustments.
- Scope item catalog queries in vendor workflows (bills, purchase orders, vendor
  credits, and catalog exports) using `purchase_account_id` to prevent
  cross-vendor item collisions while using the Zoho Inventory API.
- Deliver complete implementations; do not leave accidental placeholders,
  `pass`, or TODO markers. Intentional abstract/protocol stubs are allowed.


## Execution Environment & Fast-Path

- **Immediate Execution**: When asked to run a script, test, app, or workflow, execute it immediately on the **first turn** without reading OKF files or performing pre-flight file exploration.
- Always run Python commands and tests using the workspace virtual environment:
  - Run scripts with `.venv/bin/python <script>` (or `uv run python <script>`).
  - Run tests with `.venv/bin/pytest` (or `uv run pytest`).
- Never invoke global/system `python` or bare `pytest`.

### Workflow Command Index
| Workflow / Task | Direct Execution Command |
|---|---|
| **GSTR-2 Verification** | `.venv/bin/python apps/verify_gstr2.py` |
| **GSTR-3B vs P&L Comparison** | `.venv/bin/python apps/compare_gstr3b_pnl.py` |
| **Payment Review / Allocations** | `.venv/bin/python apps/payment_review.py` |
| **Bank Collection Reconciliation** | `.venv/bin/python apps/run_collection_reconciliation.py` |
| **Neoseal Stock Count** | `.venv/bin/python apps/neoseal_stock_count.py` |
| **Neoseal Item Audit** | `.venv/bin/python apps/audit_neoseal_items.py` |
| **Apply Neoseal Name Updates** | `.venv/bin/python apps/apply_neoseal_name_updates.py` |
| **Export Neoseal Items** | `.venv/bin/python apps/export_neoseal_items.py` |
| **Creator Customer Sync** | `.venv/bin/python apps/sync_creator_customers.py` |
| **Creator Beat Sync** | `.venv/bin/python apps/sync_creator_beats.py` |
| **Stock Transfer** | `.venv/bin/python apps/transfer_stock.py` |
| **Project Dashboard** | `.venv/bin/python apps/dashboard.py` |
| **Run All Tests** | `.venv/bin/pytest -q` |


## Safety and Verification

- Generated project artifacts default to `output/`. APIs may honor a caller's
  explicit absolute path when documented and safely validated.
- Never commit credentials, local configuration, generated output, logs, or
  `.codex` artifacts. Mock network access in unit tests; mutations require
  explicit intent and should offer dry-run behavior where practical.
- Add pytest coverage for changed normal, edge, and error paths. Tests may live
  in `tests/` or beside workflows as configured by `pyproject.toml`.
- Run the relevant tests and, when practical, the full suite. Report unrelated
  failures accurately; do not change unrelated work merely to make the suite green.

## OKF Maintenance

When a change creates durable knowledge about architecture, configuration,
operations, public APIs, compatibility, or known limitations:

Keep one documentation owner for each topic and link to it elsewhere instead
of copying detailed instructions.

1. Update the relevant OKF concept and its nearest `index.md` if needed.
2. Give each concept file (except `index.md` and `log.md`) YAML frontmatter with
   a non-empty `type`.
3. Add a concise newest-first entry to the nearest `log.md` under an ISO date.
4. Use ordinary Markdown links and exclude transient status, secrets, tokens,
   customer data, and details already obvious from the diff.

Only the root `okf/index.md` has frontmatter (`okf_version` only); `log.md` has none.
