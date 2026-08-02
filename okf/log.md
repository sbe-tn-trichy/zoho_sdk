# Knowledge Change Log

## 2026-08-02

- Consolidated the former `zoho_sdk_advanced` business workflows under `zoho.workflows` while retaining root and legacy-subpackage compatibility imports.
- Documented the one-way dependency boundary from core transport and service clients to higher-level workflows.
- Added workflow runtime configuration, credential-safety guidance, and complete local validation commands.
- Added Zoho Analytics dynamic SQL export support using asynchronous jobs, polling, and CSV result parsing.
- Established OKF v0.2 maintenance rules and excluded local `.codex` artifacts from version control.
