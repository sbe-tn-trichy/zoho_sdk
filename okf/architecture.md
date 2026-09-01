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
zoho (API Clients & Auth) <-- workflows (Business Engines) <-- apps (Web UIs & CLI Tools)
```

## Layer Boundaries

1. **Core / Client Layer (`zoho.books`, `zoho.wd`, `zoho.creator`, etc.)**:
   - Generic REST endpoint wrappers and authentication helpers.
   - Low-level clients do not import each other and do not import workflows or apps.

2. **Workflow Layer (`workflows`)**:
   - Multi-service domain engines and reconciliation algorithms.
   - Pure library code; receives client instances via dependency injection.
   - Contains no web servers, UI code, or runnable scripts.

3. **Applications Layer (`apps/`)**:
   - User-facing entry points: local HTTP review servers, dashboards, and CLI runners.
   - Imports from `workflows` and `zoho` to coordinate end-to-end execution.

4. **Ephemeral Scripts (`scripts/`)**:
   - Reserved strictly for temporary, disposable scratch scripts (TTL < 24 hours).

# Import Rules

- **Rule 1**: Lower layers (`zoho`, `workflows`) MUST NEVER import from `apps` or `scripts`.
- **Rule 2**: Subpackage encapsulation is maintained via `__init__.py` public exports (`__all__`).
