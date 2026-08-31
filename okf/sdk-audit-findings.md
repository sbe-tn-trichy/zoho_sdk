---
type: concept
title: Zoho SDK Audit Findings
description: Security, performance, and usability review and hardening across core transport and service clients.
tags: [security, performance, usability, audit, quality]
sources:
  - id: base-client
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/zoho/base_client.py
    title: Base Zoho Client
    author: team:sbe-tn-trichy
    last_modified: 2026-08-31
status: active
---

# Zoho SDK Audit & Defensive Hardening

## Overview

A comprehensive code audit across all `zoho_sdk` service clients identified key areas for defensive security improvements, performance optimizations, and usability fixes.

## Key Improvements

### 1. Security
* **Sensitive Parameter Redaction**: `sanitize_log_params()` masks sensitive query parameters (e.g. auth tokens, secrets, emails, GST numbers, PAN) in `BaseZohoClient` before logging.
* **Strict Output Path Confinement**: `resolve_output_path(strict_containment=True)` prevents path traversal and verifies destination paths remain within the designated output tree.
* **Thread-Safe Token Refresh**: Added `_token_lock` (`threading.Lock`) in `BaseZohoClient` to prevent concurrent 401 token refresh race conditions.
* **Sanitized Error Payloads**: Removed raw HTML error page formatting from exceptions to prevent internal gateway leakage.

### 2. Performance
* **Socket Cleanup on Streaming**: `Files.download` and `Messages.download_attachment` ensure streaming HTTP responses are explicitly closed to prevent connection pool exhaustion.
* **Streaming Generator-Based Pagination**: Added `list_iter()` across Books and Inventory `BaseResource` classes to yield records page-by-page without buffering entire datasets in RAM.
* **Direct File Streaming**: File download operations stream response chunks directly to disk.

### 3. Usability & Developer Experience
* **Bills Partial Update**: `Bills.update` invokes `_prepare_payload(data, check_required=False)` to allow partial field updates without requiring all creation fields.
* **Configurable Cliq Error Handling**: `ZohoCliqAPI.send_notification` supports `raise_on_error: bool = False` to allow callers to catch `ZohoCliqError` when desired.
* **Type Annotations**: Corrected `ZohoSheetAPI.list_sheets` signature to `List[str]`.
* **Structured Exception Fields**: `ZohoError` exposes `status_code`, `error_code`, `response_data`, and `endpoint`.

## Related Concepts

* [Package Architecture](architecture.md)
* [Configuration Reference](configuration.md)
* [Zoho Books Client](zoho-books.md)
* [OKF Maintenance](okf-maintenance.md)
