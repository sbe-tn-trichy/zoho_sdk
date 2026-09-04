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

# Configuration Hierarchy

Runtime configuration is loaded using a prioritized multi-tier hierarchy:

1. **Environment Variables**: Explicit process environment variables (`os.environ`).
2. **Project `.env` File**: Local `.env` in the repository root (not committed).
3. **Project `zoho_config.json` File**: Local JSON configuration profile in the project root (ignored in `.gitignore`).
4. **User Home Config (`~/.config/zoho/config.json` or `~/.zoho/config.json`)**: User-level global configuration profiles.

The first existing JSON file in that order is authoritative. Invalid JSON,
non-object configuration, and missing active profiles fail closed instead of
falling through to a lower-priority file, preventing accidental cross-tenant
identifier selection.

A configuration template is provided in `zoho_config.example.json`.

Supported configuration keys:

- `TOKEN_URL`: HTTP URL for retrieving runtime OAuth access tokens.
- `ORG_ID`: Zoho Books organization ID.
- `DOMAIN`: Zoho API data-center domain; defaults to `in`.
- `CREATOR_OWNER_NAME`: Zoho Creator account owner used by shared client factories.
  The former `CREATOR_ACCOUNT_OWNER_NAME` environment variable remains a
  compatibility fallback.
- `PAYMENT_CREATOR_APP_LINK_NAME`: Creator application link name used by the
  collection-reconciliation runner; defaults to `order-management-new`.
- `PAYMENT_CREATOR_REPORTS`: Grouped Creator report-link mapping used by the
  payment-review queue. Its `online`, `cheque`, `cheque_detail`, `customer`, and
  `checkpoint` entries default to `Online_Payments`, `Cheques`,
  `All_Cheque_Details`, `All_Customers1`, and `All_Payments`, respectively.
- `FILES_DIR`: Directory containing Polycab credit memo PDFs.
- `POLYCAB_LEDGER_PATH`: Polycab reconciliation ledger path.
- `ZEISS_LEDGER_PATH`: Zeiss reconciliation ledger path.
- `POLYCAB_FOLDER_ID`: Destination WorkDrive folder ID.
- `POLYCAB_VENDOR_ID`: Vendor ID for Polycab ledger reconciliation.
- `NEOSEAL_PURCHASE_ACCOUNT_ID`: Purchase-account ID used to scope NeoSeal item-catalog workflows.
- `NEOSEAL_PRICE_LIST_GOOGLE_SHEET_ID`: Google Sheet ID for the NeoSeal price list.
- `FAN_PURCHASE_ACCOUNT_ID`: Purchase-account ID used to scope fan item-catalog workflows.
- `ZEISS_VENDOR_ID`: Vendor ID for Zeiss ledger reconciliation.
- `ZOHO_RSO_CN_ITEM_ID`: Books item ID used for RSO credit notes.
- `ZOHO_SCHEME_CN_ITEM_ID`: Books item ID used for scheme credit notes.
- `ZOHO_GST0_TAX_ID`: Books tax ID used for out-of-scope credit notes.
- `ZOHO_TAX_SETTINGS_ID`: Books tax-settings identifier.
- `RSO_CUSTOMER_ID`: Default Books customer for imported Polycab RSO sales orders.
- `EXPECTED_LOCATION_ID`: Default Zoho Books location / branch ID.
- `EXPECTED_LOCATION_NAME`: Expected location display name.
- `BANK_ACCOUNT_IDFC`, `BANK_ACCOUNT_HDFC`, `BANK_ACCOUNT_HDFC_AGENCIES`, and
  `BANK_ACCOUNT_ICICI`: Books bank-account identifiers.
- `GSTIN_TO_VENDOR_ID`: JSON object mapping GSTIN values to vendor IDs.

# Credential Safety & Path Security

Access tokens are retrieved dynamically at runtime from `TOKEN_URL` and are not persisted in source code, logs, or reports.

Downloaded attachments, reports, and exports default to the `output/` directory.
Documented APIs may honor an explicit absolute caller path. In both cases,
`resolve_output_path()` and `sanitize_filename()` prevent directory traversal and
unsafe derived filenames.

`.env` and `zoho_config.json` are intended for local execution only and must not be committed. Prefer explicit environment or user home (`~/.config/zoho/config.json`) configuration for deployed workloads. Treat organization, vendor, item, tax, bank-account, location, and WorkDrive folder IDs as deployment-specific values without hardcoding tenant defaults in library code.

Polycab vendor-credit creation passes `EXPECTED_LOCATION_ID` explicitly in
the Zoho Books payload. Callers may override the location for a single credit
or a batch; the workflow does not rely on the Books organization default.

Polycab RSO sales-order import uses `RSO_CUSTOMER_ID` and
`EXPECTED_LOCATION_ID`. Both values are included explicitly in the creation
payload and can be overridden per import.

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

The payment-review application reads all Creator report link names from the
same configuration hierarchy. Set entries within the grouped
`payment_creator_reports` object in the active `zoho_config.json` profile to
override them without changing Python or HTML. The environment-variable form
accepts the same object encoded as JSON in `PAYMENT_CREATOR_REPORTS`.
