"""The historical commands share execution while retaining saved-view defaults."""

from unittest.mock import Mock

import pytest

from apps import create_inter_location_contra_query_table as create
from apps import manage_inter_location_contra_query_table as manage
from apps import update_inter_location_contra_query_table as update


@pytest.mark.parametrize(
    "command,argv,view_id,apply",
    [
        (manage, [], None, False),
        (create, [], None, False),
        (update, [], "264324000008274019", False),
        (update, ["--view-id", "custom", "--apply"], "custom", True),
        (create, ["--name", "Reviewed table", "--apply"], None, True),
    ],
)
def test_commands_share_execution(monkeypatch, capsys, command, argv, view_id, apply):
    client = object()
    monkeypatch.setattr(manage, "get_analytics_client", lambda **kwargs: client)
    sync = Mock(return_value={
        "validated_pair_count": 2, "preview_row_count": 3,
        "view_id": view_id or "created", "saved_row_count": 3,
    })
    monkeypatch.setattr(manage, "sync_inter_location_contra_query_table", sync)
    assert command.main(argv) == 0
    assert sync.call_args.args == (client,)
    assert sync.call_args.kwargs == {
        "workspace_id": "264324000000002043",
        "account_id": "1094368000002033114",
        "view_id": view_id,
        "name": "Reviewed table" if "--name" in argv else "Inter Location Contra FY25-27",
        "apply": apply,
    }
    output = capsys.readouterr().out
    assert ("Dry run:" in output) == (not apply)


def test_invalid_arguments_do_not_construct_client(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(manage, "get_analytics_client", factory)
    with pytest.raises(SystemExit) as error:
        update.main(["--unknown"])
    assert error.value.code == 2
    factory.assert_not_called()


def test_workflow_failure_propagates(monkeypatch):
    monkeypatch.setattr(manage, "get_analytics_client", lambda **kwargs: object())
    monkeypatch.setattr(manage, "sync_inter_location_contra_query_table", Mock(side_effect=ValueError("invalid report")))
    with pytest.raises(ValueError, match="invalid report"):
        create.main([])
