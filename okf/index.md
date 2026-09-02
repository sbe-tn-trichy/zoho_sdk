---
okf_version: "0.2"
---

# Unified Zoho SDK Knowledge

## Orientation

* [Project Overview](project-overview.md) - Unified purpose, scope, low-level clients, and workflow domain boundaries.
* [Package Architecture](architecture.md) - Layered package architecture, import direction rules, and subpackage encapsulation.

## Reference

* [Configuration Reference](configuration.md) - OAuth credentials, organization settings, environment variables, and CLI dry-run flags.
* [Zoho Books Client](zoho-books.md) - Books resource access, pagination, and customer-only contact retrieval.
* [Duplicate Customer Payment Check](duplicate-payment-check.md) - Read-only detection of customer payments sharing the same customer, date, and amount.
* [Polycab RSO Import](polycab-rso-import.md) - Parse Polycab return-sales-order PDFs, create location-scoped Books sales orders, and attach the source PDF.
* [Analytics Metadata Snapshots](analytics-metadata.md) - Complete workspace metadata collection, rate-limit handling, snapshot files, and relationship maps.
* [Bank–Vendor Ledger Matching](bank-vendor-ledger-matching.md) - Books bank-withdrawal matching and ICICI UPI reference normalization.
* [Creator Collection Reconciliation](collection-reconciliation.md) - Creator collection matching, Books customer-payment categorization, Analytics exceptions, schema contracts, and audit safety.
* [GSTR-1 Verification](gstr1-verification.md) - Previous-month invoice and credit-note checks for drafts, number continuity, chronology, and e-invoice registration.
* [Vendor-Customer Offset](vendor-customer-offset.md) - GSTIN-safe paired customer/vendor payments through a clearing bank account.
* [Creator Customer Delete-Sync](creator-customer-delete-sync.md) - Unidirectional deletion reconciliation of Creator customer records absent from Books.
* [Neoseal Item Audit](neoseal-item-audit.md) - Automated catalog data quality, duplicate/packaging twin detection, nomenclature verification, and item group audit.
* [SDK Audit Findings](sdk-audit-findings.md) - Security, performance, and usability review across core transport and service clients.
* [OKF Maintenance](okf-maintenance.md) - Rules for maintaining concept documentation, YAML frontmatter, and change logs.

## Operations

* [Development Runbook](development-runbook.md) - Local virtual environment setup, pytest runner execution, and safe workflow development guidelines.
* [Project Operations Dashboard](project-dashboard.md) - Loopback-only numbered launcher for common safe-default workflows.
