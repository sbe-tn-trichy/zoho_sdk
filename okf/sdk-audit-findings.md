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
    last_modified: 2026-09-01
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
* **Mutation Token Routing**: `POST`, `PUT`, `PATCH`, and `DELETE` use the mutation-token path by default. Semantically read-only requests that happen to use POST must explicitly pass `is_mutation=False`; Zoho Sheet worksheet listing is the current exception.

### 2. Performance
* **Socket Cleanup on Streaming**: The shared `zoho.downloads.write_response_to_file()` helper streams binary responses, rejects unsupported response shapes, and closes HTTP responses even when writing fails.
* **Streaming Generator-Based Pagination**: Added `list_iter()` across Books and Inventory `BaseResource` classes to yield records page-by-page without buffering entire datasets in RAM.
* **Direct File Streaming**: File download operations stream response chunks directly to disk.
* **Callback Memory Safety**: Completion callbacks receive `None` for streamed response bodies so binary downloads are not materialized through `response.text`.

### 3. Usability & Developer Experience
* **Bills Partial Update**: `Bills.update` invokes `_prepare_payload(data, check_required=False)` to allow partial field updates without requiring all creation fields.
* **Configurable Cliq Error Handling**: `ZohoCliqAPI.send_notification` supports `raise_on_error: bool = False` to allow callers to catch `ZohoCliqError` when desired.
* **Type Annotations**: Corrected `ZohoSheetAPI.list_sheets` signature to `List[str]`.
* **Structured Exception Fields**: `ZohoError` exposes `status_code`, `error_code`, `response_data`, and `endpoint`.
* **Uniform Request Contract**: Every concrete service client forwards the base transport options for form data, headers, files, streaming, URL overrides, mutation classification, and timeouts. Books and Inventory continue to add organization IDs without mutating caller-owned parameter dictionaries.
* **Portable Filenames**: Untrusted download names normalize both POSIX and Windows separators before basename extraction.
* **Python 3.8 Compatibility**: Runtime-evaluated WorkDrive annotations use `typing.Union` and `typing.Set`, matching the minimum version declared in `pyproject.toml`.

## Request Contract

Concrete client `request()` overrides must remain compatible with `BaseZohoClient.request()`. New transport options must be added to every override and forwarded unchanged unless the service intentionally augments the value. Regression tests exercise streaming and timeout forwarding through a real `ZohoBooksAPI` instance.

Mutation classification is based on semantics rather than legacy service-specific method lists. Unsafe HTTP methods use `CatalystAuth` mutation tokens by default. A read-like POST endpoint must opt out at its call site with `is_mutation=False` and include a test proving that it continues to use the direct read token.

## Related Concepts

* [Package Architecture](architecture.md)
* [Configuration Reference](configuration.md)
* [Zoho Books Client](zoho-books.md)
* [OKF Maintenance](okf-maintenance.md)
