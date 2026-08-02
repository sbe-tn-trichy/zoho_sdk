---
type: Concept
title: Package Architecture & Modularity
description: Layered architecture, import direction rules, and subpackage encapsulation in the merged zoho_sdk repository.
tags: [architecture, modularity, layers, imports]
sources:
  - id: package-root
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/zoho/__init__.py
    title: Package root exports
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# Layered Architecture

`zoho_sdk` enforces strict modularity through a layered architecture with one-way import rules:

```
zoho.core (Auth / Transport) <-- zoho.books / zoho.wd / zoho.creator (API Clients) <-- zoho.workflows (Business Workflows)
```

## Layer Boundaries

1. **Core Layer (`zoho.auth`, `zoho.base_client`, `zoho.exceptions`)**:
   - Handles OAuth, token HTTP requests, base API client error handling.
   - Knows nothing about Books, WorkDrive, or business workflows.

2. **Client Layer (`zoho.books`, `zoho.wd`, `zoho.creator`, etc.)**:
   - Single-service REST endpoint wrappers.
   - Low-level clients do not import each other and do not import workflows.

3. **Workflow Layer (`zoho.workflows`)**:
   - Multi-service orchestrators (e.g., Polycab credit memo pipeline using Books + WorkDrive + local PDF parser).
   - Receives client instances via dependency injection.

# Import Rules

- **Rule 1**: Lower layers (`zoho.books`, `zoho.core`) MUST NEVER import from `zoho.workflows`.
- **Rule 2**: Subpackage encapsulation is maintained via `__init__.py` public exports (`__all__`).
