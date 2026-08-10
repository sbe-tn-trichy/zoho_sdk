---
type: Project
title: Unified Project Overview
description: Scope, architecture layers, low-level REST clients, and business workflows in the merged zoho_sdk repository.
tags: [python, zoho, sdk, workflows, reconciliation]
sources:
  - id: readme
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/README.md
    title: Unified Repository README
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# Purpose

`zoho_sdk` distributes low-level REST API clients under `zoho` and higher-level domain workflows under the parallel top-level `workflows` package.

# Architecture Scope

The unified source tree contains two distinct layers:

1. **Low-Level API Clients (`zoho.books`, `zoho.creator`, `zoho.wd`, `zoho.analytics`, `zoho.inventory`, `zoho.sheet`, `zoho.cliq`, `zoho.mail`)**:
   - Generic REST wrappers around raw Zoho HTTP endpoints.
   - Authentication managers (`ZohoOAuth2Manager`, `CatalystAuth`, `HttpTokenProvider`).

2. **High-Level Domain Workflows (`workflows`)**:
   - `workflows.bank_reconciliation`: Bank transaction and ledger matching.
   - `workflows.collection_reconciliation`: Incoming Creator collection matching, Books customer-payment categorization, Analytics-assisted exceptions, and Creator audit records.
   - `workflows.gstr1_verification`: Read-only previous-month Books invoice and credit-note readiness checks for drafts, numbering, chronology, and e-invoice registration.
   - `workflows.vendor_ledger_reconciliation`: Vendor ledger cleaning, matching, and Zeiss statement parsing.
   - `workflows.polycab_credit_memos`: Polycab credit memo PDF extraction, Zoho Books creation, attachment uploads, and WorkDrive uploads.

# Package Layout

`zoho` and `workflows` are independent top-level packages under `src/`. The former `zoho_sdk_advanced` compatibility package has been removed.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [Development Runbook](development-runbook.md).
