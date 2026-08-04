---
type: Reference
title: Configuration Reference
description: Runtime configuration, environment variables, organization identifiers, and credential handling in zoho_sdk.
tags: [configuration, environment, credentials]
sources:
  - id: config-module
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/core/config.py
    title: Workflow Configuration module
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# Environment Variables

Runtime configuration is loaded via environment variables or a local `.env` file:

- `TOKEN_URL`: HTTP URL for retrieving runtime OAuth access tokens.
- `ORG_ID`: Zoho Books organization ID.
- `DOMAIN`: Zoho API data-center domain; defaults to `in`.
- `FILES_DIR`: Directory containing Polycab credit memo PDFs.
- `POLYCAB_LEDGER_PATH`: Polycab reconciliation ledger path.
- `ZEISS_LEDGER_PATH`: Zeiss reconciliation ledger path.
- `POLYCAB_FOLDER_ID`: Destination WorkDrive folder ID.
- `POLYCAB_VENDOR_ID`: Vendor ID for Polycab ledger reconciliation.
- `ZEISS_VENDOR_ID`: Vendor ID for Zeiss ledger reconciliation.
- `ZOHO_RSO_CN_ITEM_ID`: Books item ID used for RSO credit notes.
- `ZOHO_SCHEME_CN_ITEM_ID`: Books item ID used for scheme credit notes.
- `ZOHO_GST0_TAX_ID`: Books tax ID used for out-of-scope credit notes.
- `ZOHO_TAX_SETTINGS_ID`: Books tax-settings identifier.
- `EXPECTED_LOCATION_ID`: Default Zoho Books location / branch ID.
- `EXPECTED_LOCATION_NAME`: Expected location display name.
- `BANK_ACCOUNT_IDFC`, `BANK_ACCOUNT_HDFC`, `BANK_ACCOUNT_HDFC_AGENCIES`, and
  `BANK_ACCOUNT_ICICI`: Books bank-account identifiers.
- `GSTIN_TO_VENDOR_ID`: JSON object mapping GSTIN values to vendor IDs.

# Credential Safety

Access tokens are retrieved dynamically at runtime from `TOKEN_URL` and are not persisted in source code, logs, or reports.

`.env` is intended for local execution only and must not be committed. Prefer explicit environment configuration for deployed workloads. Treat organization, vendor, item, tax, bank-account, location, and WorkDrive folder IDs as deployment-specific values even where development defaults exist.

# Collection Reconciliation Configuration

`CollectionReconciliationConfig` is explicit rather than environment-backed.
Callers provide the Creator app link name and Books bank-account ID, plus
optional Creator form/report names, Analytics workspace and SQL template, date
and amount tolerances, and `dry_run`. Deployment code remains responsible for
constructing the three authenticated clients and choosing the organization and
data-center domain.

Use `dry_run=True` for the initial scheduled execution. Books custom-field
creation requires the separate explicit
`create_missing_books_fields=True` option on schema validation or the workflow
entry point.
