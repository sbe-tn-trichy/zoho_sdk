"""Google Sheets SDK exceptions."""
from __future__ import annotations


class GoogleSheetsError(Exception):
    """Base exception for Google Sheets SDK operations."""

    def __init__(self, message: str, *, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class GoogleSheetsAuthError(GoogleSheetsError):
    """Raised when authentication credentials are missing, invalid, or expired."""


class SpreadsheetNotFoundError(GoogleSheetsError):
    """Raised when the specified Google Spreadsheet cannot be found."""


class WorksheetNotFoundError(GoogleSheetsError):
    """Raised when the specified worksheet/tab is not found in the spreadsheet."""
