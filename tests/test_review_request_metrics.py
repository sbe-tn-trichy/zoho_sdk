from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.request_metrics import RequestMetrics


def test_service_counts_and_existing_callback_are_preserved():
    metrics = RequestMetrics()
    previous = MagicMock()
    books = SimpleNamespace(on_request_completed=previous)
    analytics = SimpleNamespace(on_request_completed=None)
    metrics.attach(books, "books")
    metrics.attach(analytics, "analytics")
    with metrics.operation("refresh") as counts:
        books.on_request_completed("GET", "invoices", None, 200, "private payload")
        analytics.on_request_completed("GET", "", None, 200, "private payload")
        assert dict(counts) == {"books": 1, "analytics": 1}
    previous.assert_called_once()
    books.on_request_completed("GET", "invoices", None, 200, "private payload")
    assert counts["books"] == 1


def test_failure_logs_counts_without_payloads_and_resets_context(caplog):
    metrics = RequestMetrics()
    books = SimpleNamespace(on_request_completed=None)
    metrics.attach(books, "books")
    with caplog.at_level("INFO"), pytest.raises(RuntimeError):
        with metrics.operation("accept"):
            books.on_request_completed("POST", "customerpayments", {}, 400, "secret")
            raise RuntimeError("failed")
    assert "total=1" in caplog.text
    assert "secret" not in caplog.text
    with metrics.operation("refresh") as counts:
        assert not counts


def test_force_refresh_route_keeps_confirmation_and_passes_cache_bypass():
    import io
    import json
    from apps.payment_review import make_handler

    service = MagicMock()
    service.refresh.return_value = {"entries": [], "preview_cache_hits": {}}
    service.load.return_value = service.refresh.return_value
    handler_cls = make_handler(service, "token", RequestMetrics())
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/api/refresh"
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    for confirmed in (False, True):
        body = json.dumps({"confirm": confirmed, "force_refresh": True}).encode()
        handler.headers = {"X-Review-Token": "token", "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.do_POST()
        if not confirmed:
            service.refresh.assert_not_called()
    service.refresh.assert_called_once_with(force_refresh=True)


def test_preview_cache_avoids_real_sdk_export_requests(tmp_path):
    from zoho.base_client import BaseZohoClient
    from zoho.analytics.resources import Queries
    from workflows.collection_reconciliation import OnlinePaymentReviewConfig, OnlinePaymentReviewService

    client = BaseZohoClient("test-token", "com", "https://analyticsapi.zoho.com/restapi/v2", "analytics")
    payloads = [
        {"data": {"jobId": "job"}},
        {"data": {"jobStatus": "JOB COMPLETED"}},
        {"data": []},
    ] * 2
    responses = []
    for payload in payloads:
        response = MagicMock(status_code=200)
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = payload
        responses.append(response)
    client.session.request = MagicMock(side_effect=responses)
    metrics = RequestMetrics()
    metrics.attach(client, "analytics")
    service = OnlinePaymentReviewService(
        MagicMock(), MagicMock(),
        OnlinePaymentReviewConfig(creator_app_link_name="app", bank_account_id="bank",
                                 analytics_workspace_id="workspace", customer_finder_view_id="view",
                                 state_path=tmp_path / "review.json"),
        SimpleNamespace(queries=Queries(client)),
    )
    with metrics.operation("cold") as cold:
        assert service._preview_customer_finder(["remitter"]) == []
    with metrics.operation("warm") as warm:
        assert service._preview_customer_finder(["remitter"]) == []
    # Posting uses the uncached lookup, with real SDK export/poll/download plumbing.
    with metrics.operation("accept") as accept:
        assert service._query_historical_customer_finder(["remitter"]) == []
    assert dict(cold) == {"analytics": 3}
    assert dict(warm) == {}
    assert dict(accept) == {"analytics": 3}
    assert client.session.request.call_count == 6
    client.close()
