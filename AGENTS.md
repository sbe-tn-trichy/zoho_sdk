# Repository Guidance

This repository maintains durable project knowledge as a Google Open Knowledge
Format (OKF) v0.2 bundle in [`okf/`](okf/).

Before planning or implementing a multi-file or behavior-changing task:

1. Read [`okf/index.md`](okf/index.md).
2. Open the concepts relevant to the task.
3. Treat the code and tests as authoritative when they conflict with the bundle.
4. Correct stale OKF concepts as part of the same change.

When a change creates durable knowledge about architecture, configuration,
operations, public APIs, or known limitations:

1. Add or update the relevant OKF concept.
2. Ensure every concept file (all `.md` files except reserved `index.md` and
   `log.md`) begins with valid YAML frontmatter containing a non-empty `type`.
3. Add new concepts to the nearest `index.md`.
4. Record a concise, newest-first entry in the nearest `log.md` under an ISO
   `YYYY-MM-DD` heading.
5. Use ordinary Markdown links for relationships between concepts.

Do not add frontmatter to `index.md` except for `okf_version` at the bundle
root. Do not add frontmatter to `log.md`. Avoid copying transient task status,
secrets, tokens, or customer data into the bundle.
