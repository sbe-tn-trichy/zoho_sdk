"""Unit tests for Google Sheets SDK."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError
import httplib2
import pytest

from google_sheets import (
    DEFAULT_SCOPES,
    READONLY_SCOPES,
    GoogleSheetsAuthError,
    GoogleSheetsClient,
    GoogleSheetsError,
    SpreadsheetNotFoundError,
    create_credentials,
)
from workflows.core.auth import get_google_sheets_client


def test_create_credentials_with_access_token():
    creds = create_credentials(access_token="test-access-token")
    assert creds.token == "test-access-token"
    assert list(creds.scopes) == list(DEFAULT_SCOPES)


def test_create_credentials_with_custom_scopes():
    creds = create_credentials(access_token="test-access-token", scopes=READONLY_SCOPES)
    assert creds.token == "test-access-token"
    assert list(creds.scopes) == list(READONLY_SCOPES)


def test_create_credentials_empty_token_raises():
    with pytest.raises(GoogleSheetsAuthError, match="Provided access_token is empty"):
        create_credentials(access_token="   ")


def test_create_credentials_with_service_account_info():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    fake_info = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": pem,
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds = create_credentials(service_account_info=fake_info)
    assert creds.service_account_email == "test@test-project.iam.gserviceaccount.com"


def test_create_credentials_with_service_account_file(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    fake_info = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": pem,
        "client_email": "file-test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    sa_file = tmp_path / "service_account.json"
    sa_file.write_text(json.dumps(fake_info), encoding="utf-8")

    creds = create_credentials(service_account_file=sa_file)
    assert creds.service_account_email == "file-test@test-project.iam.gserviceaccount.com"



def test_create_credentials_service_account_file_missing(tmp_path):
    missing_file = tmp_path / "nonexistent.json"
    with pytest.raises(GoogleSheetsAuthError, match="Service account file not found"):
        create_credentials(service_account_file=missing_file)


def test_create_credentials_from_env_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "env-token-xyz")
    creds = create_credentials()
    assert creds.token == "env-token-xyz"


def test_create_credentials_from_google_access_token(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "fallback-token-abc")
    creds = create_credentials()
    assert creds.token == "fallback-token-abc"


def test_create_credentials_missing_all(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(GoogleSheetsAuthError, match="No Google credentials provided"):
        create_credentials()


def test_client_validation():
    mock_service = MagicMock()
    client = GoogleSheetsClient(service=mock_service)

    with pytest.raises(ValueError, match="Spreadsheet ID must be a non-empty string"):
        client.get_spreadsheet("")

    with pytest.raises(ValueError, match="Invalid spreadsheet ID format"):
        client.get_spreadsheet("invalid id with spaces")

    with pytest.raises(ValueError, match="Invalid spreadsheet ID format"):
        client.get_spreadsheet("bad/id/with/slashes")


def test_client_get_spreadsheet():
    mock_service = MagicMock()
    mock_get = MagicMock()
    mock_service.spreadsheets.return_value.get.return_value = mock_get
    mock_get.execute.return_value = {
        "spreadsheetId": "valid-sheet-123",
        "properties": {"title": "Test Sheet"},
    }

    client = GoogleSheetsClient(service=mock_service)
    result = client.get_spreadsheet("valid-sheet-123", fields="properties.title")

    mock_service.spreadsheets.return_value.get.assert_called_once_with(
        spreadsheetId="valid-sheet-123",
        includeGridData=False,
        fields="properties.title",
    )
    assert result["properties"]["title"] == "Test Sheet"


def test_client_get_sheet_ids():
    mock_service = MagicMock()
    mock_get = MagicMock()
    mock_service.spreadsheets.return_value.get.return_value = mock_get
    mock_get.execute.return_value = {
        "sheets": [
            {"properties": {"title": "Summary", "sheetId": 0}},
            {"properties": {"title": "Data", "sheetId": 42}},
        ]
    }

    client = GoogleSheetsClient(service=mock_service)
    sheet_ids = client.get_sheet_ids("valid-sheet-123")
    assert sheet_ids == {"Summary": 0, "Data": 42}


def test_client_get_values():
    mock_service = MagicMock()
    mock_values_get = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.get.return_value = mock_values_get
    mock_values_get.execute.return_value = {
        "range": "Sheet1!A1:B2",
        "values": [["Col1", "Col2"], [10, 20]],
    }

    client = GoogleSheetsClient(service=mock_service)
    values = client.get_values("sheet-id-1", "Sheet1!A1:B2")

    mock_service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId="sheet-id-1",
        range="Sheet1!A1:B2",
        valueRenderOption="FORMATTED_VALUE",
        dateTimeRenderOption="SERIAL_NUMBER",
    )
    assert values == [["Col1", "Col2"], [10, 20]]


def test_client_batch_get_values():
    mock_service = MagicMock()
    mock_batch_get = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.batchGet.return_value = mock_batch_get
    mock_batch_get.execute.return_value = {
        "valueRanges": [
            {"range": "Sheet1!A1:A2", "values": [[1], [2]]},
            {"range": "Sheet2!B1:B2", "values": [[3], [4]]},
        ]
    }

    client = GoogleSheetsClient(service=mock_service)
    result = client.batch_get_values("sheet-id-1", ["Sheet1!A1:A2", "Sheet2!B1:B2"])

    assert result == {
        "Sheet1!A1:A2": [[1], [2]],
        "Sheet2!B1:B2": [[3], [4]],
    }

    # Empty ranges returns empty dict immediately without calling API
    assert client.batch_get_values("sheet-id-1", []) == {}


def test_client_update_values():
    mock_service = MagicMock()
    mock_update = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.update.return_value = mock_update
    mock_update.execute.return_value = {"updatedCells": 4}

    client = GoogleSheetsClient(service=mock_service)
    resp = client.update_values("sheet-id-1", "Sheet1!A1:B2", [[1, 2], [3, 4]])

    mock_service.spreadsheets.return_value.values.return_value.update.assert_called_once_with(
        spreadsheetId="sheet-id-1",
        range="Sheet1!A1:B2",
        valueInputOption="RAW",
        body={"range": "Sheet1!A1:B2", "values": [[1, 2], [3, 4]]},
    )
    assert resp["updatedCells"] == 4


def test_client_batch_update_values_mapping():
    mock_service = MagicMock()
    mock_batch_update = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.batchUpdate.return_value = mock_batch_update
    mock_batch_update.execute.return_value = {"totalUpdatedCells": 2}

    client = GoogleSheetsClient(service=mock_service)
    data = {
        "Sheet1!A1": [[10]],
        "Sheet1!B2": [[20]],
    }
    resp = client.batch_update_values("sheet-id-1", data, value_input_option="USER_ENTERED")

    mock_service.spreadsheets.return_value.values.return_value.batchUpdate.assert_called_once_with(
        spreadsheetId="sheet-id-1",
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": "Sheet1!A1", "values": [[10]]},
                {"range": "Sheet1!B2", "values": [[20]]},
            ],
        },
    )
    assert resp["totalUpdatedCells"] == 2


def test_client_append_and_clear_values():
    mock_service = MagicMock()
    mock_append = MagicMock()
    mock_clear = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.append.return_value = mock_append
    mock_service.spreadsheets.return_value.values.return_value.clear.return_value = mock_clear
    mock_append.execute.return_value = {"updates": {"updatedRows": 1}}
    mock_clear.execute.return_value = {"clearedRange": "Sheet1!A1:B2"}

    client = GoogleSheetsClient(service=mock_service)
    append_resp = client.append_values("sheet-id-1", "Sheet1!A1", [["val1", "val2"]])
    assert append_resp["updates"]["updatedRows"] == 1

    clear_resp = client.clear_values("sheet-id-1", "Sheet1!A1:B2")
    assert clear_resp["clearedRange"] == "Sheet1!A1:B2"


def test_client_batch_update():
    mock_service = MagicMock()
    mock_batch = MagicMock()
    mock_service.spreadsheets.return_value.batchUpdate.return_value = mock_batch
    mock_batch.execute.return_value = {"replies": []}

    client = GoogleSheetsClient(service=mock_service)
    requests = [{"updateCells": {"fields": "userEnteredValue"}}]
    resp = client.batch_update("sheet-id-1", requests)

    mock_service.spreadsheets.return_value.batchUpdate.assert_called_once_with(
        spreadsheetId="sheet-id-1",
        body={"requests": requests, "includeSpreadsheetInResponse": False},
    )
    assert resp["replies"] == []


def test_client_error_handling_404():
    mock_service = MagicMock()
    resp = httplib2.Response({"status": 404})
    content = json.dumps({"error": {"message": "Spreadsheet not found", "code": 404}}).encode("utf-8")
    http_error = HttpError(resp, content)

    mock_service.spreadsheets.return_value.get.return_value.execute.side_effect = http_error

    client = GoogleSheetsClient(service=mock_service)
    with pytest.raises(SpreadsheetNotFoundError, match="Spreadsheet not found: missing-sheet"):
        client.get_spreadsheet("missing-sheet")


def test_client_error_handling_general():
    mock_service = MagicMock()
    resp = httplib2.Response({"status": 400})
    content = json.dumps({"error": {"message": "Invalid range", "code": 400}}).encode("utf-8")
    http_error = HttpError(resp, content)

    mock_service.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = http_error

    client = GoogleSheetsClient(service=mock_service)
    with pytest.raises(GoogleSheetsError, match="Google Sheets API error: Invalid range") as exc_info:
        client.get_values("sheet-id-1", "bad_range")
    assert exc_info.value.status_code == 400


def test_workflows_core_auth_factory(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "factory-token")
    client = get_google_sheets_client()
    assert isinstance(client, GoogleSheetsClient)
    assert client.credentials.token == "factory-token"
