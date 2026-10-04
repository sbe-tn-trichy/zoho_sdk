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

The runner accepts a reviewed YAML or JSON configuration whose `mappings` array maps
each source to exact current and previous year input cells. A source can be a
stable list of Books account IDs (`account_ids`) or a scalar report response
path (`source_path`). Supported
reports are `profitandloss` and `balancesheet`. Each mapping has `report`,
`sheet`, `current_cell`, `previous_cell`, and optional `multiplier`. Use `-1` as
the multiplier when a note convention reverses the Books sign. Account IDs are
preferable to names or array positions because report display order can change.

The spreadsheet ID, required Books location scope, and reviewed mappings are
maintained separately from application code in the Git-ignored file
`config/accounting-mapping.yaml`. An editable template is in
`config/accounting-mapping.example.yaml`; copy it to the local mapping
file, set `spreadsheet_id` and `location_ids`, replace each account placeholder
with a reviewed Books account ID, and add mappings for every other required
note input. Reports always use `TransactionDate.CustomDate`, accrual basis, all
rows, and the configured comma-separated Books location IDs. In the P&L notes,
the current FY 2025–26 column is G and the comparison FY 2024–25 column is E.

The optional `equity` section maps owner account IDs to the owner name, opening
balance, interest, withdrawals, other net movement, and closing formula cells
in Note 3. It supplies `excluded_location_id` for the equity ledger's branch
rule, `interest_account_id` for interest classification, and
`withdrawal_transaction_types` for owner withdrawals. The updater calls
`zoho.helpers.fetch_equity_general_ledger`, which uses one bulk-filtered Books
register query for all equity accounts. For each configured owner, it sums
credits minus debits, gets the opening and closing amounts from the
location-scoped Books balance sheets, and refuses updates unless opening plus
movement equals closing. Equity credits offsetting the configured Interest
Expense account populate the interest column. Equity debits in the configured
withdrawal transaction types populate withdrawals. The remaining movement is
written to the explicitly unclassified column; remuneration and profit remain
unclassified. The existing closing formulas are preserved. Configure the
residual heading with `movement_header_cell` and `movement_header`.

`--equity-only` limits a preview or apply run to this section. During `--apply`,
the updater verifies that every configured closing cell still contains a
formula before writing any equity values. The current mapping uses four owner
rows in `Note 1 to 3` and excludes the SBE location from the ledger.

Before preparing report values, every run fetches and combines the active and
inactive Books charts of accounts into `output/books_accounts.sqlite3`. For each mapping with
`account_ids`, it resolves the IDs against that fresh snapshot and atomically
refreshes the parallel `account_names` array in the mapping file. Unknown IDs fail the
run, so changing an ID cannot leave a stale name unnoticed.

Example mapping entry (replace the account ID with a reviewed Books account):

```json
{
  "spreadsheet_id": "GOOGLE_SPREADSHEET_ID",
  "location_ids": ["BOOKS_LOCATION_ID"],
  "mappings": [
    {"report":"profitandloss","account_ids":["BOOKS_ACCOUNT_ID"],"account_names":["AUTO_REFRESHED_ACCOUNT_NAME"],"sheet":"Notes to P & L 19 to 25","current_cell":"G6","previous_cell":"E6"}
  ]
}
```

Run `.venv/bin/python apps/update_books_statement_sheet.py` for a preview using
the dedicated YAML mapping, then rerun with `--apply` after reviewing the
output. A different mapping path can still be supplied as the positional
argument when needed. Add `--equity-only` to preview or update only the owner
capital note.

The workflow fetches each report and period once, rejects missing sources,
duplicate destinations, bad report dates, and formula overwrite. Map detailed
note input cells; statement totals are linked by formulas in the workbook.
Accounting classifications, split disclosures, and values not available in
Books reports need review before their mappings are added. The template itself
contains some pre-existing broken references, which this updater does not edit.

The FY 2025–26 live P&L note was populated from the branch-excluded Books P&L
account totals in column G. The statement's current-year detail lines again
reference note totals. Note 21 presents Books purchase accounts and its generic
Cost of Goods Sold account as separate lines because the API report does not
provide an opening/purchases/closing inventory roll-forward. Note 23 separates
partner interest using Note 3; its remaining interest lacks a loan-type split.
The miscellaneous expense line includes signed purchase-discount and stock-transfer
offsets. These note classifications require accounting review.

The ignored YAML mapping now also contains `pnl_notes`: stable Books account-ID
groups for all FY 2025–26 P&L note input cells, the excluded branch, dates, and
the Note 3 partner-interest source. Run
`.venv/bin/python apps/update_books_statement_sheet.py --pnl-only` to preview
the current-year note values when `GOOGLE_SHEETS_ACCESS_TOKEN` is set; for an
offline Sheets preview, supply `--partner-interest AMOUNT`. Add `--apply` to
read current Note 3 partner interest and write the 19 mapped note inputs in one
batch after checking that none is a formula. The workflow fetches one Books P&L
report, computes disclosed residuals, and leaves all note and statement total
formulas intact. Review the classification groups when new Books accounts are
added or material account usage changes.

The YAML retains accounting calculation and workbook-row sections used by other
tooling. Account-name refresh preserves these sections and writes YAML atomically
(formatting and comments may be normalized). Explicit JSON mapping paths remain
supported. Install the workflows extra for PyYAML.
