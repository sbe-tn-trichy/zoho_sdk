from unittest.mock import MagicMock, patch

import pytest

from workflows.core.auth import get_token_for, get_workdrive_client
from workflows.core.exceptions import ZohoAuthError


@patch("workflows.core.auth.HttpTokenProvider")
def test_get_token_for_preserves_broker_failure(provider_class):
    provider_class.return_value.get_tokens.side_effect = RuntimeError("offline")

    with pytest.raises(ZohoAuthError, match="Unable to retrieve"):
        get_token_for("books", token_url="http://tokens")


@patch("workflows.core.auth.ZohoWorkdriveAPI")
@patch("workflows.core.auth.get_token_for")
def test_workdrive_factory_configures_refresh(get_token, client_class):
    get_token.side_effect = ["initial", "refreshed"]

    client = get_workdrive_client(token_url="http://tokens")

    assert client is client_class.return_value
    callback = client_class.call_args.kwargs["token_refresh_callback"]
    assert callback() == "refreshed"
    assert get_token.call_args_list[0].args[:2] == (
        "workdrive",
        "zoho_workdrive_conn",
    )
