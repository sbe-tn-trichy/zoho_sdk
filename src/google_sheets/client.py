"""Google Sheets API client."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from google.auth.credentials import Credentials as BaseCredentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from .auth import DEFAULT_SCOPES, create_credentials
from .exceptions import (
    GoogleSheetsError,
    SpreadsheetNotFoundError,
    WorksheetNotFoundError,
)

SPREADSHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class GoogleSheetsClient:
    """High-level client for Google Sheets API v4.

    Wraps the official ``google-api-python-client`` discovery service with typed,
    convenient methods for workbook metadata, batch range reads, updates, and modifications.
    """

    def __init__(
        self,
        credentials: BaseCredentials | None = None,
        *,
        service: Resource | None = None,
        access_token: str | None = None,
        service_account_file: str | Path | None = None,
        service_account_info: Mapping[str, Any] | None = None,
        scopes: Sequence[str] | None = None,
    ) -> None:
        """Initialize Google Sheets client.

        Args:
            credentials: Pre-constructed Google credentials.
            service: Optional pre-constructed googleapiclient discovery Resource (e.g., for testing).
            access_token: OAuth 2.0 access token string.
            service_account_file: Path to a service account JSON credentials file.
            service_account_info: Dictionary containing service account credentials JSON.
            scopes: OAuth 2.0 scopes (defaults to full spreadsheets scope).
        """
        if service is not None:
            self._service = service
            self._credentials = credentials
            return

        if credentials is None:
            credentials = create_credentials(
                access_token=access_token,
                service_account_file=service_account_file,
                service_account_info=service_account_info,
                scopes=scopes or DEFAULT_SCOPES,
            )

        self._credentials = credentials
        self._service = build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )

    @property
    def service(self) -> Resource:
        """The underlying googleapiclient discovery Resource."""
        return self._service

    @property
    def credentials(self) -> BaseCredentials | None:
        """The credentials used by this client."""
        return self._credentials

    def _validate_spreadsheet_id(self, spreadsheet_id: str) -> str:
        """Validate spreadsheet ID format to prevent malformed API calls."""
        if not spreadsheet_id or not isinstance(spreadsheet_id, str):
            raise ValueError("Spreadsheet ID must be a non-empty string.")
        if not SPREADSHEET_ID_PATTERN.fullmatch(spreadsheet_id):
            raise ValueError(f"Invalid spreadsheet ID format: {spreadsheet_id!r}")
        return spreadsheet_id

    def _handle_http_error(self, exc: HttpError, spreadsheet_id: str = "") -> None:
        """Translate Google API HttpError into SDK exceptions."""
        status = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else None
        error_details: dict[str, Any] = {}
        error_message = str(exc)

        try:
            if hasattr(exc, "content") and exc.content:
                parsed = json.loads(exc.content.decode("utf-8"))
                error_details = parsed.get("error", {})
                error_message = error_details.get("message", error_message)
        except Exception:
            pass

        if status == 404:
            raise SpreadsheetNotFoundError(
                f"Spreadsheet not found: {spreadsheet_id or 'unknown'} ({error_message})",
                status_code=status,
                details=error_details,
            ) from exc

        raise GoogleSheetsError(
            f"Google Sheets API error: {error_message}",
            status_code=status,
            details=error_details,
        ) from exc

    def get_spreadsheet(
        self,
        spreadsheet_id: str,
        *,
        fields: str | None = None,
        include_grid_data: bool = False,
    ) -> dict[str, Any]:
        """Fetch metadata for a spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            fields: Partial field mask (e.g. ``'sheets.properties'``).
            include_grid_data: Whether to include grid data in the response.

        Returns:
            Spreadsheet resource dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        kwargs: dict[str, Any] = {
            "spreadsheetId": sid,
            "includeGridData": include_grid_data,
        }
        if fields:
            kwargs["fields"] = fields

        try:
            return self._service.spreadsheets().get(**kwargs).execute()
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def get_sheet_ids(self, spreadsheet_id: str) -> dict[str, int]:
        """Fetch a mapping of sheet title to sheetId integer for all worksheets.

        Args:
            spreadsheet_id: The ID of the spreadsheet.

        Returns:
            Dict mapping sheet title to its numeric sheet ID.
        """
        meta = self.get_spreadsheet(spreadsheet_id, fields="sheets.properties")
        sheets = meta.get("sheets", [])
        return {
            sheet["properties"]["title"]: int(sheet["properties"]["sheetId"])
            for sheet in sheets
            if "properties" in sheet and "title" in sheet["properties"] and "sheetId" in sheet["properties"]
        }

    def get_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        *,
        value_render_option: str = "FORMATTED_VALUE",
        date_time_render_option: str = "SERIAL_NUMBER",
    ) -> list[list[Any]]:
        """Fetch cell values from a single range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range_name: Qualified or unqualified A1 notation range (e.g. ``'Sheet1!A1:B10'``).
            value_render_option: One of ``'FORMATTED_VALUE'``, ``'UNFORMATTED_VALUE'``, or ``'FORMULA'``.
            date_time_render_option: One of ``'SERIAL_NUMBER'`` or ``'FORMATTED_STRING'``.

        Returns:
            List of rows, where each row is a list of cell values.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=sid,
                    range=range_name,
                    valueRenderOption=value_render_option,
                    dateTimeRenderOption=date_time_render_option,
                )
                .execute()
            )
            return response.get("values", [])
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def batch_get_values(
        self,
        spreadsheet_id: str,
        ranges: Sequence[str],
        *,
        value_render_option: str = "FORMATTED_VALUE",
        date_time_render_option: str = "SERIAL_NUMBER",
    ) -> dict[str, list[list[Any]]]:
        """Fetch cell values from multiple ranges in a single request.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            ranges: Sequence of range names in A1 notation.
            value_render_option: One of ``'FORMATTED_VALUE'``, ``'UNFORMATTED_VALUE'``, or ``'FORMULA'``.
            date_time_render_option: One of ``'SERIAL_NUMBER'`` or ``'FORMATTED_STRING'``.

        Returns:
            Dictionary mapping requested range name to list of rows.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        if not ranges:
            return {}

        try:
            response = (
                self._service.spreadsheets()
                .values()
                .batchGet(
                    spreadsheetId=sid,
                    ranges=list(ranges),
                    valueRenderOption=value_render_option,
                    dateTimeRenderOption=date_time_render_option,
                )
                .execute()
            )
            result: dict[str, list[list[Any]]] = {}
            for value_range in response.get("valueRanges", []):
                result[value_range.get("range", "")] = value_range.get("values", [])
            return result
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def update_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        """Write values to a single range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range_name: Range in A1 notation.
            values: 2D array of values to write.
            value_input_option: One of ``'RAW'`` or ``'USER_ENTERED'``.

        Returns:
            UpdateValuesResponse dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        body = {
            "range": range_name,
            "values": [list(row) for row in values],
        }
        try:
            return (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=sid,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def batch_update_values(
        self,
        spreadsheet_id: str,
        data: Sequence[dict[str, Any]] | Mapping[str, Sequence[Sequence[Any]]],
        *,
        value_input_option: str = "RAW",
    ) -> dict[str, Any]:
        """Write values to multiple ranges in a single request.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            data: Either a list of ValueRange dicts (``[{'range': ..., 'values': [...]}]``),
                  or a mapping of ``{range_address: 2d_values_array}``.
            value_input_option: One of ``'RAW'`` or ``'USER_ENTERED'``.

        Returns:
            BatchUpdateValuesResponse dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)

        value_ranges: list[dict[str, Any]] = []
        if isinstance(data, Mapping):
            for address, rows in data.items():
                value_ranges.append({
                    "range": address,
                    "values": [list(row) for row in rows],
                })
        else:
            for item in data:
                value_ranges.append({
                    "range": item["range"],
                    "values": [list(row) for row in item.get("values", [])],
                })

        body = {
            "valueInputOption": value_input_option,
            "data": value_ranges,
        }

        try:
            return (
                self._service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=sid,
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: Sequence[Sequence[Any]],
        *,
        value_input_option: str = "RAW",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict[str, Any]:
        """Append values to a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range_name: A1 notation range to search for a table.
            values: 2D array of values to append.
            value_input_option: One of ``'RAW'`` or ``'USER_ENTERED'``.
            insert_data_option: One of ``'OVERWRITE'`` or ``'INSERT_ROWS'``.

        Returns:
            AppendValuesResponse dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        body = {
            "range": range_name,
            "values": [list(row) for row in values],
        }
        try:
            return (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sid,
                    range=range_name,
                    valueInputOption=value_input_option,
                    insertDataOption=insert_data_option,
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def clear_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> dict[str, Any]:
        """Clear values in a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range_name: A1 notation range to clear.

        Returns:
            ClearValuesResponse dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        try:
            return (
                self._service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=sid,
                    range=range_name,
                    body={},
                )
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise

    def batch_update(
        self,
        spreadsheet_id: str,
        requests: Sequence[dict[str, Any]],
        *,
        include_spreadsheet_in_response: bool = False,
    ) -> dict[str, Any]:
        """Execute a batch of update requests (e.g. formatting, updateCells, addSheet).

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            requests: Sequence of Request objects (e.g. ``[{'updateCells': ...}]``).
            include_spreadsheet_in_response: Whether to include the updated spreadsheet state.

        Returns:
            BatchUpdateSpreadsheetResponse dict.
        """
        sid = self._validate_spreadsheet_id(spreadsheet_id)
        body = {
            "requests": list(requests),
            "includeSpreadsheetInResponse": include_spreadsheet_in_response,
        }
        try:
            return (
                self._service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=sid,
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc, sid)
            raise
