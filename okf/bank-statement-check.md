---
type: operations
description: Read-only HDFC CSV completeness comparison with the Analytics Books bank-statement replica.
---

# HDFC statement completeness helper

[bank_statement_check.py](../src/workflows/bank_statement_check.py) parses an HDFC
seven-column CSV and compares it with Bank Statements (Zoho Books) through an
injected Analytics client. Run the helper with:

```bash
.venv/bin/python apps/check_hdfc_statement.py /absolute/path/statement.csv
```

The configured HDFC Books account is the default; `--account-id` selects another
explicit account. Workspace and table IDs are configurable with `--workspace-id`
and `--view-id`. Their defaults are workspace `264324000000002043` and table
`264324000005829009`. The CSV supplies the inclusive posting-date range. The
Analytics SQL filters by account and range, includes all statement statuses, and
uses the table name and required columns from `AnalyticsCatalog`. It never
refreshes metadata. `--catalog-dir` defaults to `workspace_metadata/<workspace-id>`;
a successful prior metadata sync is required. Default and configurable view
references are registered explicitly. No shared query tables are modified.

CSV reference strings retain leading zeros. Amounts use exact Decimal INR values;
malformed dates, malformed rows, invalid amounts, duplicate source IDs, unexpected
Analytics directions, and account/date scope mismatches fail with context.
For this Analytics source, debit means deposit and credit means withdrawal.

Matches require the same posting date, direction and amount, plus reference or
full narration identity. Numeric reference leading zeros and narration case or
whitespace are ignored. A full numeric reference retained as a whole token in
Books narration can establish identity. Account digit masking is accepted only
when the otherwise complete narration agrees. A maximum one-to-one match keeps
duplicate multiplicity; each Books line is consumed once.

Shortened cheque narrations require special treatment: a matching retained
clearing prefix and masked reference suffix, together with date/direction/amount,
produce a **probable** match only when the pair is unique on both sides. Suffix
collisions remain review items. These are weaker evidence than full identity.

Results distinguish:

- `matched`: full reference/narration evidence.
- `probable`: unique masked cheque evidence; full identity remains unavailable.
- `missing`: no Books line with the same date, direction and amount.
- `duplicate_shortfall`: insufficient distinct Books lines with matching identity;
  identical occurrences cannot identify which physical CSV row was omitted.
- `review`: date/direction/amount exists but identity differs or remains ambiguous.

Missing means absent from the Analytics replica at capture time. Analytics data
synchronization can lag live Books; metadata sync time does not establish data
freshness. A missing line is not automatically imported or categorized.

Output defaults to `output/hdfc_statement_check/`: `sources.json` contains a scoped
replay snapshot with capture and last successful metadata-sync times;
`comparison.json` includes every result and unmatched Books IDs; `report.md`
summarizes findings; `missing.csv` contains missing/count-shortage lines;
`exceptions.csv` also includes probable and review cases. Artifacts contain
financial data and remain ignored. Output must not contain source input files.

Replay without network access into a separate output directory:

```bash
.venv/bin/python apps/check_hdfc_statement.py /absolute/path/statement.csv \
  --saved output/hdfc_statement_check/sources.json \
  --output output/hdfc_statement_replay
```

Snapshots must match account, workspace, view and period. The helper performs
only remote reads and local report writes. It does not change Books, Analytics
metadata, statement imports or bank categorization.
