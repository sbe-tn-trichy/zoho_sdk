"""Regression tests for authenticated transport boundaries."""

from unittest.mock import MagicMock, patch

import pytest

from zoho.auth import ZohoOAuth2Manager
from zoho.base_client import BaseZohoClient
from zoho.exceptions import ZohoBooksError


def _client(response):
    client = BaseZohoClient("secret-token", "in", "https://www.zohoapis.in/books", "books")
    client.session = MagicMock()
    client.session.request.return_value = response
    return client


@pytest.mark.parametrize("status", [400, 500])
def test_empty_error_response_raises(status):
    response = MagicMock(status_code=status, text="", reason="Error", headers={})
    response.json.side_effect = ValueError("empty body")
    client = _client(response)

    with pytest.raises(ZohoBooksError) as caught:
        client.request("GET", "items")

    assert caught.value.status_code == status


@pytest.mark.parametrize("status", [200, 204])
def test_successful_empty_response_returns_empty_object(status):
    response = MagicMock(status_code=status, text="", headers={})
    assert _client(response).request("GET", "items") == {}


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/export",
        "http://www.zohoapis.in/books/export",
        "https://download.zoho.in.evil.example/export",
        "https://download.zoho.in:444/export",
    ],
)
def test_override_rejects_untrusted_destination_before_http(url):
    client = _client(MagicMock())
    with pytest.raises(ValueError, match="approved HTTPS Zoho host"):
        client.request("GET", "", override_url=url)
    client.session.request.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zohoapis.in/books/export",
        "https://download.zoho.in/v1/workdrive/download/file-id",
    ],
)
def test_override_allows_approved_destination(url):
    response = MagicMock(status_code=204, text="", headers={})
    client = _client(response)
    assert client.request("GET", "", override_url=url) == {}
    assert client.session.request.call_args.kwargs["url"] == url


def test_missing_refreshed_token_does_not_expose_response():
    manager = ZohoOAuth2Manager("client", "secret", "refresh")
    response = MagicMock()
    response.json.return_value = {"error": "invalid", "access_token_hint": "must-not-leak"}
    with patch("requests.post", return_value=response):
        with pytest.raises(ValueError) as caught:
            manager.refresh_access_token()
    assert "must-not-leak" not in str(caught.value)
