"""Regression tests for authenticated transport boundaries."""

from unittest.mock import MagicMock, patch

import pytest

from zoho.auth import CatalystAuth, ZohoOAuth2Manager
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


@pytest.mark.parametrize("header, delay", [("-1", 0), ("0", 0), ("3", 3), ("120", 60), ("invalid", 12)])
def test_retry_after_is_bounded_and_invalid_values_use_default(header, delay):
    limited = MagicMock(status_code=429, headers={"Retry-After": header})
    success = MagicMock(status_code=204, text="", headers={})
    client = _client(success)
    client.session.request.side_effect = [limited, success]
    with patch("zoho.base_client.time.sleep") as sleep:
        assert client.request("GET", "invoices") == {}
    sleep.assert_called_once_with(delay)
    limited.close.assert_called_once()


def test_negative_retry_after_exhaustion_raises_structured_error():
    limited = MagicMock(status_code=429, text="limited", headers={"Retry-After": "-1"})
    limited.json.return_value = {"code": 429, "message": "limited"}
    client = _client(limited)
    with patch("zoho.base_client.time.sleep") as sleep:
        with pytest.raises(ZohoBooksError) as caught:
            client.request("GET", "invoices")
    assert caught.value.status_code == 429
    assert client.session.request.call_count == 4
    assert [call.args for call in sleep.call_args_list] == [(0,), (0,), (0,)]


@pytest.mark.parametrize("method, is_mutation", [("GET", None), ("POST", None), ("POST", False)])
def test_refresh_preserves_dynamic_token_classification(method, is_mutation):
    unauthorized = MagicMock(status_code=401)
    success = MagicMock(status_code=204, text="", headers={})
    client = _client(success)
    client.session.request.side_effect = [unauthorized, success]
    refreshed = CatalystAuth("fresh-direct", "http://localhost/tokens", "books")
    client.token_refresh_callback = MagicMock(return_value=refreshed)
    headers = []

    def request(**kwargs):
        headers.append(dict(kwargs["headers"]))
        return unauthorized if len(headers) == 1 else success

    client.session.request.side_effect = request
    with patch("zoho.auth.fetch_token_from_catalyst", return_value="fresh-mutation") as broker:
        assert client.request(method, "invoices", is_mutation=is_mutation) == {}
    expected_mutation = method == "POST" and is_mutation is not False
    expected = "fresh-mutation" if expected_mutation else "fresh-direct"
    assert headers[1]["Authorization"] == f"Zoho-oauthtoken {expected}"
    assert broker.call_count == int(expected_mutation)
    assert client.access_token is refreshed
    client.token_refresh_callback.assert_called_once()
    unauthorized.close.assert_called_once()
