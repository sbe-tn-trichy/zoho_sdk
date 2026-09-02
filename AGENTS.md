# Repository Guidance

## Source of Truth

- Code and tests are authoritative. Use [`INDEX.md`](INDEX.md) only as a
  navigation aid.
- Before a multi-file or behavior-changing task, read [`okf/index.md`](okf/index.md)
  and the relevant concepts. Correct stale concepts in the same change.

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
- Books and Inventory resources reuse `zoho.base_resource.BaseResource`.
- Reuse `workflows.core.matching` conversions when their semantics fit.
- Public APIs use explicit typed parameters. Use `TypedDict` or dataclasses for
  stable structured records crossing workflow boundaries.
- Applications construct SDK clients through `workflows.core.auth` factories.
- Scope item catalog queries in vendor workflows (bills, purchase orders, vendor
  credits, and catalog exports) using `purchase_account_id` (via `books.items.list_by_purchase_account`
  or `zoho.helpers.items` helpers) to prevent cross-vendor item collisions.
- Deliver complete implementations; do not leave accidental placeholders,
  `pass`, or TODO markers. Intentional abstract/protocol stubs are allowed.


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

1. Update the relevant OKF concept and its nearest `index.md` if needed.
2. Give each concept file (except `index.md` and `log.md`) YAML frontmatter with
   a non-empty `type`.
3. Add a concise newest-first entry to the nearest `log.md` under an ISO date.
4. Use ordinary Markdown links and exclude transient status, secrets, tokens,
   customer data, and details already obvious from the diff.

Only the root `okf/index.md` has frontmatter (`okf_version` only); `log.md` has none.
