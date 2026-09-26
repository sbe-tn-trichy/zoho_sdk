---
type: operations
description: Mapping Zoho Books financial reports into a linked Google Sheets statement template.
---

# Books financial statement sheet

`apps/update_books_statement_sheet.py` updates the FY 2025–26 Google Sheets
financial statement template from Zoho Books report data. It uses the configured
Books organization and compares FY 2025–26 with FY 2024–25. It defaults to a
read-only preview; `--apply` requires a Google Sheets OAuth access token in
`GOOGLE_SHEETS_ACCESS_TOKEN` with permission to edit the workbook.

The runner accepts a reviewed JSON array mapping each source to exact current
and previous year input cells. A source can be a stable list of Books account IDs
(`account_ids`) or a scalar report response path (`source_path`). Supported
reports are `profitandloss` and `balancesheet`. Each mapping has `report`,
`sheet`, `current_cell`, `previous_cell`, and optional `multiplier`. Use `-1` as
the multiplier when a note convention reverses the Books sign. Account IDs are
preferable to names or array positions because report display order can change.

An editable sample is in `examples/books_statement_mapping.sample.json`. Replace
each placeholder with a reviewed Books account ID and add mappings for every
other required note input. In the P&L notes, the current FY 2025–26 column is
G and the comparison FY 2024–25 column is E.

Example mapping entry (replace the account ID with a reviewed Books account):

```json
[{"report":"profitandloss","account_ids":["BOOKS_ACCOUNT_ID"],"sheet":"Notes to P & L 19 to 25","current_cell":"G6","previous_cell":"E6"}]
```

Run `.venv/bin/python apps/update_books_statement_sheet.py mapping.json` for a
preview, then rerun with `--apply` after reviewing the output.

The workflow fetches each report and period once, rejects missing sources,
duplicate destinations, bad report dates, and formula overwrite. Map detailed
note input cells; statement totals are linked by formulas in the workbook.
Accounting classifications, split disclosures, and values not available in
Books reports need review before their mappings are added. The template itself
contains some pre-existing broken references, which this updater does not edit.
