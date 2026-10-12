---
type: Reference
title: Google Sheets SDK
description: Client, authentication, and range operations for Google Sheets API v4.
tags: [google-sheets, sdk, client, spreadsheets]
---

# Google Sheets SDK

The `google_sheets` package provides a high-level client and authentication helpers for Google Sheets API v4 using the official `google-api-python-client` and `google-auth` libraries.

## Public Surface

- `google_sheets.GoogleSheetsClient`: Primary client class for workbook metadata, range reading, writing, clearing, and batch updates.
- `google_sheets.create_credentials`: Constructs Google credentials supporting OAuth 2.0 access tokens and Service Account JSON files.
- `google_sheets.DEFAULT_SCOPES`: Full spreadsheet scope (`https://www.googleapis.com/auth/spreadsheets`).
- `google_sheets.READONLY_SCOPES`: Read-only spreadsheet scope (`https://www.googleapis.com/auth/spreadsheets.readonly`).
- `google_sheets.exceptions`: `GoogleSheetsError`, `GoogleSheetsAuthError`, `SpreadsheetNotFoundError`, `WorksheetNotFoundError`.
- `workflows.core.auth.get_google_sheets_client`: Application factory constructing `GoogleSheetsClient` using runtime `Config` or environment variables.

## Authentication

Authentication resolves in the following priority:

1. Explicit `access_token` passed to client / factory.
2. Explicit `service_account_file` or `service_account_info` passed to client / factory.
3. `GOOGLE_SHEETS_ACCESS_TOKEN` or `GOOGLE_ACCESS_TOKEN` environment variable.
4. `GOOGLE_APPLICATION_CREDENTIALS` environment variable pointing to a service account JSON file.

## Operations

- `client.get_spreadsheet(spreadsheet_id, fields=...)`: Fetch workbook properties and sheets.
- `client.get_sheet_ids(spreadsheet_id)`: Return a mapping of `{sheet_title: sheet_id_integer}`.
- `client.get_values(spreadsheet_id, range_name, value_render_option=...)`: Read a single 2D range.
- `client.batch_get_values(spreadsheet_id, ranges, value_render_option=...)`: Read multiple ranges in one request.
- `client.update_values(spreadsheet_id, range_name, values, value_input_option=...)`: Write 2D values to a single range.
- `client.batch_update_values(spreadsheet_id, data, value_input_option=...)`: Batch write values using either list of `ValueRange` objects or a `{range: 2D_values}` mapping.
- `client.append_values(spreadsheet_id, range_name, values)`: Append rows to a table.
- `client.clear_values(spreadsheet_id, range_name)`: Clear values in a range.
- `client.batch_update(spreadsheet_id, requests)`: Execute arbitrary batchUpdate requests (`updateCells`, formatting, row insertion).
- `client.service`: Direct access to the underlying `googleapiclient.discovery.Resource` for unconstrained API calls.
