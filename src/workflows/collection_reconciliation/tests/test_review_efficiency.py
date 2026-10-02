"""Request reduction and freshness contracts for the review workflow."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from workflows.collection_reconciliation import OnlinePaymentReviewConfig, OnlinePaymentReviewService
from workflows.core.exceptions import ReconciliationError


@pytest.fixture
def review(tmp_path):
    creator, books, analytics = MagicMock(), MagicMock(), MagicMock()
    config = OnlinePaymentReviewConfig(
        creator_app_link_name="app", bank_account_id="bank",
        analytics_workspace_id="workspace", customer_finder_view_id="view",
        state_path=tmp_path / "review.json",
    )
    payment = {"ID": "payment", "Payment_Date": "2026-10-01",
               "Payment_Amount": "100", "Reference": "ref",
               "Customer_Name": {"ID": "customer", "Name": "Example Customer"}}
    creator.get_all_records.side_effect = lambda app, report: (
        [{"ID": "customer", "Customer_Id": "books-customer"}]
        if report == config.customer_report_link_name else [payment]
    )
    books.bank_transactions.list_all.return_value = [
        {"transaction_id": "tx", "date": "2026-10-01", "amount": 100,
         "reference_number": "ref", "description": "UPI/example@okaxis"}
    ]
    books.invoices.list_all.return_value = [
        {"invoice_id": "invoice", "balance": 100, "status": "overdue"}
    ]
    analytics.queries.execute.return_value = []
    return OnlinePaymentReviewService(creator, books, config, analytics)


def test_cold_warm_and_force_refresh_request_counts(review):
    cold = review.refresh()
    assert review.creator.get_all_records.call_count == 2
    assert review.analytics.queries.execute.call_count == 1
    assert cold["entries"][0]["reviewable"]
    warm = review.refresh()
    assert review.creator.get_all_records.call_count == 3
    assert review.analytics.queries.execute.call_count == 1
    assert warm["preview_cache_hits"]["customer_mapping"] == 1
    assert warm["preview_cache_hits"]["analytics_tokens"] > 0
    # Banks and invoice balances still refresh each time.
    assert review.books.bank_transactions.list_all.call_count == 2
    assert review.books.invoices.list_all.call_count == 2
    review.refresh(force_refresh=True)
    assert review.creator.get_all_records.call_count == 5
    assert review.analytics.queries.execute.call_count == 2
    review.analytics.views.export_all.assert_not_called()


def test_expiry_and_new_tokens(review):
    with patch("workflows.collection_reconciliation.preview_cache.monotonic", return_value=10):
        review.refresh()
    with patch("workflows.collection_reconciliation.preview_cache.monotonic", return_value=11):
        review._preview_customer_finder(["example@okaxis", "newremitter"])
    assert "newremitter" in review.analytics.queries.execute.call_args.args[1]
    assert "example@okaxis" not in review.analytics.queries.execute.call_args.args[1]
    with patch("workflows.collection_reconciliation.preview_cache.monotonic", return_value=311):
        review.refresh()
    assert review.creator.get_all_records.call_count == 4
    assert review.analytics.queries.execute.call_count == 3


def test_history_cache_scope_and_positive_results(review):
    row = {"Customer Name": "Example Customer", "Description": "example@okaxis"}
    review.analytics.queries.execute.return_value = [row]
    assert review._preview_customer_finder(["example@okaxis"]) == [row]
    assert review._preview_customer_finder(["example@okaxis"]) == [row]
    assert review.analytics.queries.execute.call_count == 1
    review.config = replace(review.config, analytics_workspace_id="other")
    review._preview_customer_finder(["example@okaxis"])
    assert review.analytics.queries.execute.call_count == 2
    review.config = replace(review.config, customer_finder_view_id="other-view")
    review._preview_customer_finder(["example@okaxis"])
    assert review.analytics.queries.execute.call_count == 3
    # A different organization's client has a separate cache scope.
    review.analytics = MagicMock()
    review.analytics.queries.execute.return_value = []
    assert review._preview_customer_finder(["example@okaxis"]) == []
    review.analytics.queries.execute.assert_called_once()


def test_conflict_skips_invoices_and_accept_bypasses_preview_cache(review):
    review.refresh()
    review.analytics.queries.execute.return_value = [
        {"Customer Name": "Other Customer", "Description": "example@okaxis"}
    ]
    with pytest.raises(ReconciliationError, match="Conflict"):
        review.accept_and_push("payment")
    assert review.analytics.queries.execute.call_count == 2
    review.books.customer_payments.create.assert_not_called()
    review.books.invoices.list_all.reset_mock()
    batch = review.refresh(force_refresh=True)
    assert not batch["entries"][0]["reviewable"]
    review.books.invoices.list_all.assert_not_called()


def test_repeat_accept_needs_no_external_reads(review):
    batch = review.refresh()
    batch["entries"][0]["push_status"] = "pushed"
    review._save(batch)
    review.analytics.reset_mock()
    review.books.reset_mock()
    assert review.accept_and_push("payment")["push_status"] == "pushed"
    assert not review.analytics.mock_calls
    assert not review.books.mock_calls


def test_query_failure_falls_back_and_failed_fallback_is_not_cached(review):
    review.analytics.queries.execute.side_effect = RuntimeError("query failed")
    review.analytics.views.export_all.side_effect = RuntimeError("export failed")
    with pytest.raises(RuntimeError, match="export failed"):
        review.refresh()
    review.analytics.views.export_all.side_effect = None
    review.analytics.views.export_all.return_value = []
    review.refresh()
    assert review.analytics.queries.execute.call_count == 2
    assert review.analytics.views.export_all.call_count == 2


def test_sql_batch_limits_and_escaping(review):
    review.config = replace(review.config, analytics_batch_tokens=100)
    tokens = [f"remitter{i}" for i in range(70)]
    assert len(review._historical_queries(tokens)) == 1
    review.config = replace(review.config, analytics_batch_tokens=35)
    assert len(review._historical_queries(tokens)) == 2
    review.config = replace(review.config, analytics_max_sql_bytes=256)
    queries = review._historical_queries(["é" * 20, "O'Brien", "another-remitter" * 2])
    assert all(len(q.encode()) <= 256 for q in queries)
    assert any("O''Brien" in q for q in queries)
    with pytest.raises(ReconciliationError, match="SQL budget"):
        review._query_historical_customer_finder(["x" * 256])
    review.analytics.views.export_all.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"analytics_batch_tokens": 0}, {"analytics_max_sql_bytes": 255},
    {"analytics_preview_ttl_seconds": -1}, {"customer_mapping_ttl_seconds": float("nan")},
])
def test_invalid_cache_configuration(kwargs):
    with pytest.raises(ValueError):
        OnlinePaymentReviewConfig(creator_app_link_name="app", **kwargs)


def test_travel_account_reuse_and_rejection_invalidation(review):
    bank = {"date": "2026-10-01", "amount": 100, "description": "NEFT/person/TA",
            "debit_or_credit": "credit", "reference_number": "ref"}
    review.books.bank_transactions.list_all.return_value = [
        {**bank, "transaction_id": f"ta-{i}"} for i in range(3)
    ]
    review.books.chart_of_accounts.list_all.return_value = [
        {"account_name": "Employee Travel Expense", "account_id": "expense",
         "account_type": "expense", "is_active": True}
    ]
    review.books.bank_transactions.categorize_as_expense.return_value = {"code": 0}
    review.refresh()
    review.categorize_travel_expense("ta-0")
    review.books.bank_transactions.categorize_as_expense.return_value = {"code": 1}
    with pytest.raises(ReconciliationError, match="rejected"):
        review.categorize_travel_expense("ta-1")
    assert review.books.chart_of_accounts.list_all.call_count == 1
    review.books.bank_transactions.categorize_as_expense.return_value = {"code": 0}
    review.categorize_travel_expense("ta-1")
    assert review.books.chart_of_accounts.list_all.call_count == 2


def test_full_export_fallback_preview_stays_consistent_when_warm(review):
    review.analytics.queries.execute.side_effect = RuntimeError("unavailable")
    rows = [{"Customer Name": "Example Customer", "Description": "historical unrelated description"}]
    review.analytics.views.export_all.return_value = rows
    assert review._preview_customer_finder(["first-remitter"]) == rows
    assert review._preview_customer_finder(["new-remitter"]) == rows
    review.analytics.views.export_all.assert_called_once()


def test_malformed_fallback_cannot_poison_cache(review):
    review.analytics.queries.execute.side_effect = RuntimeError("unavailable")
    review.analytics.views.export_all.return_value = {"error": "bad export"}
    for _ in range(2):
        with pytest.raises(ReconciliationError, match="invalid export"):
            review._preview_customer_finder(["remitter"])
    assert review.analytics.views.export_all.call_count == 2
