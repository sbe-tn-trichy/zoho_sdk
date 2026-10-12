"""Google Sheets SDK for reading, writing, and formatting Google Spreadsheets."""
from __future__ import annotations

from .auth import DEFAULT_SCOPES, READONLY_SCOPES, create_credentials
from .client import GoogleSheetsClient
from .exceptions import (
    GoogleSheetsAuthError,
    GoogleSheetsError,
    SpreadsheetNotFoundError,
    WorksheetNotFoundError,
)

__all__ = [
    "GoogleSheetsClient",
    "create_credentials",
    "DEFAULT_SCOPES",
    "READONLY_SCOPES",
    "GoogleSheetsError",
    "GoogleSheetsAuthError",
    "SpreadsheetNotFoundError",
    "WorksheetNotFoundError",
]
