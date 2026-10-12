"""Authentication helpers for Google Sheets API."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from google.auth.credentials import Credentials as BaseCredentials
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from .exceptions import GoogleSheetsAuthError

DEFAULT_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
READONLY_SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


def create_credentials(
    *,
    access_token: str | None = None,
    service_account_file: str | Path | None = None,
    service_account_info: Mapping[str, Any] | None = None,
    scopes: Sequence[str] | None = None,
) -> BaseCredentials:
    """Create Google credentials from an access token, service account, or environment.

    Resolution order:
    1. Explicit ``access_token`` argument.
    2. Explicit ``service_account_file`` argument.
    3. Explicit ``service_account_info`` argument (dict).
    4. ``GOOGLE_SHEETS_ACCESS_TOKEN`` or ``GOOGLE_ACCESS_TOKEN`` environment variable.
    5. ``GOOGLE_APPLICATION_CREDENTIALS`` environment variable pointing to a service account JSON file.

    Raises:
        GoogleSheetsAuthError: If no valid credential source is found or credentials cannot be loaded.
    """
    effective_scopes = list(scopes) if scopes is not None else list(DEFAULT_SCOPES)

    if access_token:
        token = access_token.strip()
        if not token:
            raise GoogleSheetsAuthError("Provided access_token is empty.")
        return OAuth2Credentials(token=token, scopes=effective_scopes)

    if service_account_file:
        path = Path(service_account_file).expanduser().resolve()
        if not path.is_file():
            raise GoogleSheetsAuthError(f"Service account file not found: {path}")
        try:
            return ServiceAccountCredentials.from_service_account_file(
                str(path),
                scopes=effective_scopes,
            )
        except Exception as exc:
            raise GoogleSheetsAuthError(f"Failed to load service account credentials from {path}: {exc}") from exc

    if service_account_info is not None:
        try:
            return ServiceAccountCredentials.from_service_account_info(
                dict(service_account_info),
                scopes=effective_scopes,
            )
        except Exception as exc:
            raise GoogleSheetsAuthError(f"Failed to load service account credentials from dict: {exc}") from exc

    env_token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN") or os.environ.get("GOOGLE_ACCESS_TOKEN")
    if env_token and env_token.strip():
        return OAuth2Credentials(token=env_token.strip(), scopes=effective_scopes)

    env_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_creds and env_creds.strip():
        creds_path = Path(env_creds.strip()).expanduser().resolve()
        if not creds_path.is_file():
            raise GoogleSheetsAuthError(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {creds_path}")
        try:
            return ServiceAccountCredentials.from_service_account_file(
                str(creds_path),
                scopes=effective_scopes,
            )
        except Exception as exc:
            raise GoogleSheetsAuthError(f"Failed to load credentials from {creds_path}: {exc}") from exc

    raise GoogleSheetsAuthError(
        "No Google credentials provided. Supply access_token, service_account_file, "
        "or set GOOGLE_SHEETS_ACCESS_TOKEN / GOOGLE_APPLICATION_CREDENTIALS."
    )
