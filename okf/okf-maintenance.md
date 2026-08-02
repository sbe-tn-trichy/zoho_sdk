---
type: Process
title: OKF Maintenance
description: Rules for keeping the repository's OKF v0.2 knowledge bundle accurate and reviewable.
tags: [okf, documentation, governance, maintenance]
sources:
  - id: repository-guidance
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/AGENTS.md
    title: Repository guidance
    author: team:sbe-tn-trichy
    last_modified: 2026-08-02
status: active
---

# When to Update OKF

Update the bundle in the same change whenever code alters durable knowledge about:

- package architecture or import boundaries;
- public APIs and compatibility guarantees;
- authentication or runtime configuration;
- operational procedures, validation commands, or known limitations.

Transient task status, credentials, customer data, generated output, and implementation notes that are already obvious from a local diff do not belong in OKF.

# Concept Requirements

Every concept file except `index.md` and `log.md` must begin with YAML frontmatter containing a non-empty `type`. Keep titles, descriptions, tags, sources, and status current. Add each new concept to the nearest `index.md` using an ordinary relative Markdown link.

The bundle root `index.md` contains only the `okf_version` frontmatter key. `log.md` has no frontmatter.

# Change Log

Record concise, newest-first entries in `log.md` beneath an ISO `YYYY-MM-DD` heading. Describe durable architectural, configuration, compatibility, or operational changes rather than reproducing the commit diff.

# Review Checklist

1. Read `index.md` and the concepts affected by the change.
2. Compare documentation with code and tests; code and tests are authoritative.
3. Correct stale concepts in the same pull request.
4. Check links, frontmatter, public names, paths, and commands.
5. Confirm no secrets, tokens, customer records, or generated artifacts were added.

# Related Knowledge

See [Unified Project Overview](project-overview.md), [Package Architecture](architecture.md), and [Development Runbook](development-runbook.md).
