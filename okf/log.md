# Knowledge Change Log

## 2026-08-02

- Moved business workflows from `src/zoho/workflows` to the parallel top-level `src/workflows` package and removed the `zoho_sdk_advanced` compatibility shim.
- Hardened the Polycab workflow against duplicate uploads and attachments, strict PDF parsing failures, ignored vendor/account inputs, and unsafe Catalyst fallback behavior.
- Restricted Analytics row exports to validated CSV/JSON formats and made workflow dependencies optional and lazily loaded.
- Consolidated the former `zoho_sdk_advanced` business workflows under `workflows` while retaining root and legacy-subpackage compatibility imports.
- Documented the one-way dependency boundary from core transport and service clients to higher-level workflows.
- Added workflow runtime configuration, credential-safety guidance, and complete local validation commands.
- Added Zoho Analytics dynamic SQL export support using asynchronous jobs, polling, and CSV result parsing.
- Established OKF v0.2 maintenance rules and excluded local `.codex` artifacts from version control.
