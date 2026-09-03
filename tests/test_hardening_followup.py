import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workflows.core.auth import get_creator_client
from workflows.core.config import Config, _load_config_dict
from workflows.core.exceptions import ZohoAuthError
from workflows.core.matching import reconcile_rows
from zoho.base_client import BaseZohoClient
from zoho.exceptions import ZohoBooksError


def test_project_configuration_precedes_user_configuration(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    (home / ".config" / "zoho").mkdir(parents=True)
    (project / "zoho_config.json").write_text(
        json.dumps({"org_id": "project-org"}), encoding="utf-8"
    )
    (home / ".config" / "zoho" / "config.json").write_text(
        json.dumps({"org_id": "home-org"}), encoding="utf-8"
    )

    assert _load_config_dict(project, home)["org_id"] == "project-org"


def test_invalid_high_priority_configuration_does_not_fall_back(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    (home / ".config" / "zoho").mkdir(parents=True)
    (project / "zoho_config.json").write_text("{invalid", encoding="utf-8")
    (home / ".config" / "zoho" / "config.json").write_text(
        json.dumps({"org_id": "wrong-tenant"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="zoho_config.json"):
        _load_config_dict(project, home)


def test_invalid_active_profile_is_rejected(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "zoho_config.json").write_text(
        json.dumps({"active_profile": "missing", "profiles": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing"):
        _load_config_dict(project, tmp_path / "home")


def test_purchase_account_ids_load_from_active_profile(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "zoho_config.json").write_text(
        json.dumps(
            {
                "active_profile": "production",
                "profiles": {
                    "production": {
                        "neoseal_purchase_account_id": "neoseal-account",
                        "neoseal_price_list_google_sheet_id": "neoseal-price-list",
                        "fan_purchase_account_id": "fan-account",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_config_dict(project, tmp_path / "home")

    assert loaded["neoseal_purchase_account_id"] == "neoseal-account"
    assert loaded["neoseal_price_list_google_sheet_id"] == "neoseal-price-list"
    assert loaded["fan_purchase_account_id"] == "fan-account"


def test_example_config_covers_public_config_keys():
    project_root = Path(__file__).resolve().parent.parent
    example = json.loads(
        (project_root / "zoho_config.example.json").read_text(encoding="utf-8")
    )
    profile = example["profiles"][example["active_profile"]]
    example_keys = {key.upper() for key in profile}
    config_keys = {
        key
        for key in vars(Config)
        if key.isupper() and key != "PROJECT_ROOT"
    }

    assert config_keys <= example_keys


def test_creator_owner_must_be_explicit_or_configured():
    with patch.object(Config, "CREATOR_OWNER_NAME", ""):
        with pytest.raises(ZohoAuthError, match="CREATOR_OWNER_NAME"):
            get_creator_client(token="token")


def test_creator_owner_uses_configuration():
    with patch.object(Config, "CREATOR_OWNER_NAME", "configured-owner"):
        client = get_creator_client(token="token")
    assert client.account_owner_name == "configured-owner"


def _error_response(status_code: int, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Content-Type": "application/json"}
    response.text = json.dumps(payload or {"message": "failed"})
    response.json.return_value = payload or {"message": "failed"}
    return response


def test_failed_stream_is_closed_and_retains_endpoint():
    client = BaseZohoClient("token", "in", "https://example.invalid", "books")
    client.session = MagicMock()
    response = _error_response(500)
    client.session.request.return_value = response

    with pytest.raises(ZohoBooksError) as caught:
        client.request("GET", "reports/export", stream=True)

    response.close.assert_called_once_with()
    assert caught.value.endpoint == "reports/export"


def test_nonstream_error_retains_endpoint():
    client = BaseZohoClient("token", "in", "https://example.invalid", "books")
    client.session = MagicMock()
    client.session.request.return_value = _error_response(400)

    with pytest.raises(ZohoBooksError) as caught:
        client.request("GET", "invoices/123")

    assert caught.value.endpoint == "invoices/123"


def test_concurrent_unauthorized_requests_refresh_once():
    client = BaseZohoClient(
        "old-token",
        "in",
        "https://example.invalid",
        "books",
    )
    barrier = threading.Barrier(2)
    refresh_count = 0
    refresh_count_lock = threading.Lock()

    def refresh():
        nonlocal refresh_count
        with refresh_count_lock:
            refresh_count += 1
        return "new-token"

    def request(**kwargs):
        authorization = kwargs["headers"]["Authorization"]
        if authorization.endswith("old-token"):
            barrier.wait(timeout=2)
            return _error_response(401)
        response = MagicMock()
        response.status_code = 204
        response.headers = {}
        response.text = ""
        return response

    client.token_refresh_callback = refresh
    client.session = MagicMock()
    client.session.request.side_effect = request
    errors = []

    def worker():
        try:
            client.request("GET", "items")
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert errors == []
    assert not any(thread.is_alive() for thread in threads)
    assert refresh_count == 1


def test_weaker_match_rejects_populated_reference_conflict():
    left = {
        "date": date(2026, 1, 1),
        "amount": "100",
        "ref": "REF-A",
        "raw": "left",
    }
    right = {
        "date": date(2026, 1, 1),
        "amount": "100",
        "ref": "REF-B",
        "raw": "right",
    }

    result = reconcile_rows(
        [left],
        [right],
        reference_matches=lambda a, b: a["ref"] == b["ref"],
        reference_conflicts=lambda a, b: bool(
            a["ref"] and b["ref"] and a["ref"] != b["ref"]
        ),
        date_tolerance_days=0,
    )

    assert result["strong_matches"] == []
    assert result["matched_left_indices"] == set()


def test_core_auth_import_does_not_require_workflow_extras():
    script = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.split('.')[0] in {'pdfplumber', 'xlrd', 'openpyxl', 'pandas'}:
        raise ImportError('blocked optional dependency')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
import workflows.core.auth
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
