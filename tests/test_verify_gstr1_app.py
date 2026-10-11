import json
from unittest.mock import MagicMock

import pytest

from apps import verify_gstr1 as app


@pytest.mark.parametrize("force_refresh", [False, True])
@pytest.mark.parametrize("passed", [False, True])
def test_cli_selects_document_client_and_analytics_hsn_client(monkeypatch, tmp_path, force_refresh, passed):
    books, analytics, verifier = MagicMock(), MagicMock(), MagicMock()
    verifier.return_value = {"data_source": "books" if force_refresh else "analytics",
                             "overall_passed": passed}
    monkeypatch.setattr(app, "get_books_client", books)
    monkeypatch.setattr(app, "get_analytics_client", analytics)
    monkeypatch.setattr(app, "verify_gstr1", verifier)
    renderer = MagicMock(return_value="# GSTR-1 report\n")
    monkeypatch.setattr(app, "render_markdown_report", renderer)
    output = tmp_path / "report.md"
    json_output = tmp_path / "report.json"
    arguments = ["verify_gstr1", "--month", "2026-07", "--output", str(output),
                 "--json-output", str(json_output)]
    if force_refresh:
        arguments.append("--force-refresh")
    monkeypatch.setattr("sys.argv", arguments)
    assert app.main() == (0 if passed else 1)
    assert books.call_count == int(force_refresh)
    assert analytics.call_count == 1
    assert verifier.call_args.kwargs["force_refresh"] is force_refresh
    assert output.read_text() == "# GSTR-1 report\n"
    renderer.assert_called_once_with(verifier.return_value, gstin_aliases=app.Config.GSTIN_ALIASES)
    assert json.loads(json_output.read_text()) == verifier.return_value


def test_cli_defaults_to_markdown_without_json(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["verify_gstr1"])
    monkeypatch.setattr(app, "get_analytics_client", MagicMock())
    monkeypatch.setattr(app, "verify_gstr1", MagicMock(return_value={"data_source": "analytics", "overall_passed": True}))
    monkeypatch.setattr(app, "render_markdown_report", MagicMock(return_value="# Report\n"))
    assert app.main() == 0
    assert (tmp_path / "output/gstr1_verification.md").read_text() == "# Report\n"
    assert not list((tmp_path / "output").glob("*.json"))
