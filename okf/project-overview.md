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

`zoho_sdk` is a unified Python package containing low-level REST API clients for Zoho services and higher-level domain workflows (formerly `zoho_sdk_advanced`).

# Architecture Scope

The unified source tree contains two distinct layers:

1. **Low-Level API Clients (`zoho.books`, `zoho.creator`, `zoho.wd`, `zoho.analytics`, `zoho.inventory`, `zoho.sheet`, `zoho.cliq`, `zoho.mail`)**:
   - Generic REST wrappers around raw Zoho HTTP endpoints.
   - Authentication managers (`ZohoOAuth2Manager`, `CatalystAuth`, `HttpTokenProvider`).

2. **High-Level Domain Workflows (`zoho.workflows`)**:
   - `zoho.workflows.bank_reconciliation`: Bank transaction and ledger matching.
   - `zoho.workflows.vendor_ledger_reconciliation`: Vendor ledger cleaning, matching, and Zeiss statement parsing.
   - `zoho.workflows.polycab_credit_memos`: Polycab credit memo PDF extraction, Zoho Books creation, attachment uploads, and WorkDrive uploads.

# Backward Compatibility

To maintain compatibility with legacy codebases, `zoho_sdk_advanced` is exposed as a root module alias pointing to `zoho.workflows`.

# Related Knowledge

See [Package Architecture](architecture.md), [Configuration Reference](configuration.md), and [Development Runbook](development-runbook.md).
