# Gemini Repository Instructions

Follow [`AGENTS.md`](AGENTS.md) as the canonical repository policy.

## Operational Principles

- **Fast Execution**: When asked to run a script, app, test, or workflow, execute the command directly via `.venv/bin/python` or `.venv/bin/pytest` immediately on the first turn without pre-flight exploration or reading OKF files.
- **OKF Consultation**: Read [`okf/index.md`](okf/index.md) and relevant concept documents only before multi-file or behavior-changing code refactors/features, never for execution requests.
- **Source of Truth**: Use [`INDEX.md`](INDEX.md) for navigation only; when documentation differs from implementation, code and tests are authoritative. Keep concepts and [`okf/log.md`](okf/log.md) updated with any changes.
- **Tooling Discipline**: Prioritize built-in file and search tools (`view_file`, `list_dir`, `grep_search`, `find_by_name`) over shell commands to avoid unnecessary interactive permission prompts.
- **Architecture & Scoping**: Strictly honor the package hierarchy (`zoho <- workflows <- apps`), base resource conventions (`BaseResource`), and query scoping rules (such as `purchase_account_id` scoping in vendor workflows).
- **Execution Environment**: Always invoke the virtual environment explicitly (`.venv/bin/python` or `.venv/bin/pytest`, or `uv run`). Never invoke system/global `python` or bare `pytest`.

