"""Request budgets and accounting equivalence for the efficiency improvements."""

import json
from datetime import date, timedelta
from decimal import Decimal
from random import Random
from unittest.mock import MagicMock, patch

import pytest

from workflows.collection_reconciliation import CollectionReconciler, CollectionReconciliationConfig
from workflows.collection_reconciliation.transaction_index import TransactionIndex
from workflows.core import HttpAttemptMetrics, OperationCounts, RequestMetrics
from workflows.core.exceptions import ReconciliationError
from workflows.creator_customer_sync import CreatorCustomerSyncConfig, sync_creator_customers
from workflows.gstr2_verification import GSTR2Verifier
from zoho.books import ZohoBooksAPI
from zoho.creator import ZohoCreatorAPI
from zoho.exceptions import ZohoBooksError


def response(status, payload):
    result = MagicMock(status_code=status, text=json.dumps(payload))
    result.headers = {"Content-Type": "application/json", "Retry-After": "0"}
    result.json.return_value = payload
    return result


def test_metrics_distinguish_retries_from_completed_calls_and_keep_callbacks(caplog):
    client = ZohoBooksAPI("token", "org")
    previous_attempt = MagicMock()
    client.on_http_attempt = previous_attempt
    client.session.request = MagicMock(side_effect=[
        response(429, {"message": "limited"}), response(200, {"invoices": []}),
        OSError("private network text"),
    ])
    metrics = RequestMetrics()
    metrics.attach(client, "books")
    with caplog.at_level("INFO"), metrics.operation("refresh") as counts:
        with patch("zoho.base_client.time.sleep"):
            client.request("GET", "invoices/private-id")
        metrics.cache_hit("customer_mapping", 2)
        with pytest.raises(OSError):
            client.request("GET", "invoices/private-id")
    assert dict(counts) == {"books": 1}
    assert counts.http.requests == {"books/invoices detail": 3}
    assert counts.http.statuses == {"books/429": 1, "books/200": 1, "books/error": 1}
    assert counts.cache_hits == {"customer_mapping": 2}
    assert counts.elapsed_seconds >= 0
    assert previous_attempt.call_count == 3
    assert "private-id" not in " ".join(record.message for record in caplog.records
                                        if record.name == "root")
    with metrics.operation("next") as fresh:
        assert not fresh.http.requests
    client.close()


def test_gst_worker_metrics_include_transport_retry_and_all_details():
    client = ZohoBooksAPI("token", "org")
    client.session.request = MagicMock(side_effect=[
        response(429, {"code": 429}),
        response(200, {"invoice": {"invoice_id": "one", "line_items": []}}),
    ])
    metrics = RequestMetrics()
    metrics.attach(client, "books")
    with metrics.operation("gst") as counts, patch("zoho.base_client.time.sleep"):
        details = client.gst._fetch_details_concurrently(
            client.invoices, [{"invoice_id": "one"}], "invoice_id", "invoice")
    assert len(details) == 1
    assert dict(counts) == {"books": 1}
    assert counts.http.requests == {"books/invoices detail": 2}
    client.close()


def test_metric_counters_remain_copyable_and_exclude_creator_and_sheet_identifiers():
    counts = OperationCounts({"books": 2})
    assert counts.copy() == {"books": 2}
    metrics = HttpAttemptMetrics()
    metrics.on_attempt("creator", "POST", "data/private-owner/private-app/form/private-form", 1, 200)
    metrics.on_attempt("sheet", "POST", "private-workbook", 1, 200)
    assert set(metrics.requests) == {"creator/creator form", "sheet/workbook"}


@pytest.mark.parametrize("payload", [{}, {"invoice": None},
    {"invoice": {"invoice_id": "wrong", "line_items": []}},
    {"invoice": {"invoice_id": "one"}}])
def test_gst_rejects_missing_mismatched_and_incomplete_details(payload):
    client = MagicMock()
    client.invoices.get.return_value = payload
    from zoho.books.resources.gst import GST
    with pytest.raises(ZohoBooksError, match="incomplete"):
        GST(client)._fetch_details_concurrently(
            client.invoices, [{"invoice_id": "one"}], "invoice_id", "invoice")


@pytest.mark.parametrize("docs", [[{}], [{"invoice_id": "one"}] * 2])
def test_gst_rejects_invalid_list_before_detail_calls(docs):
    client = MagicMock()
    from zoho.books.resources.gst import GST
    with pytest.raises(ZohoBooksError, match="missing or duplicate"):
        GST(client)._fetch_details_concurrently(client.invoices, docs, "invoice_id", "invoice")
    client.invoices.get.assert_not_called()


def sync_clients(count):
    books, creator = MagicMock(), MagicMock()
    books.contacts.list_all.return_value = [
        {"contact_id": str(i), "contact_name": f"Customer {i}", "contact_type": "customer"}
        for i in range(count)]
    creator.get_all_records.return_value = [{"ID": "orphan", "Customer_Id": "absent"}]
    creator.add_records_bulk.side_effect = lambda app, form, rows: ZohoCreatorAPI.add_records_bulk(
        creator, app, form, rows)
    creator.add_records.side_effect = lambda app, form, payload: {
        "code": 3000, "result": [{"code": 3000, "data": {"ID": "created-" + row["Customer_Id"]}}
                                 for row in payload["data"]]}
    creator.delete_records.return_value = {"code": 3000}
    return books, creator


def sync_config(tmp_path, dry_run=False):
    return CreatorCustomerSyncConfig("app", "report", form_link_name="form", dry_run=dry_run,
                                     output_dir=tmp_path, max_deletion_percentage=100)


def checkpoint(tmp_path):
    paths = list(tmp_path.glob("creator_customer_sync_*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


def test_customer_create_request_budget_and_checkpoint_before_each_batch(tmp_path):
    books, creator = sync_clients(401)
    real_add = creator.add_records.side_effect

    def add(app, form, payload):
        saved = checkpoint(tmp_path)
        assert saved["status"] == "RUNNING"
        for row in payload["data"]:
            assert next(change for change in saved["records"]
                        if change["customer_key"] == row["Customer_Id"])["action"] == "UNKNOWN"
        return real_add(app, form, payload)

    creator.add_records.side_effect = add
    result = sync_creator_customers(books, creator, sync_config(tmp_path))
    assert [len(call.args[2]["data"]) for call in creator.add_records.call_args_list] == [200, 200, 1]
    assert result["created_count"] == 401
    assert result["deleted_count"] == 1
    assert result["status"] == checkpoint(tmp_path)["status"] == "COMPLETE"
    assert all(row.get("creator_record_id") for row in result["records"])
    books.contacts.get.assert_not_called()


def test_partial_customer_batch_records_successes_and_stops_deletions(tmp_path):
    books, creator = sync_clients(201)
    successful = creator.add_records.side_effect

    def add(app, form, payload):
        result = successful(app, form, payload)
        result["result"][10] = {"code": 3001, "error": "rejected"}
        return result

    creator.add_records.side_effect = add
    with pytest.raises(ReconciliationError, match="batch incomplete"):
        sync_creator_customers(books, creator, sync_config(tmp_path))
    saved = checkpoint(tmp_path)
    assert saved["status"] == "FAILED"
    assert saved["created_count"] == 199
    assert saved["records"][10]["action"] == "FAILED"
    assert saved["records"][200]["action"] == "PLANNED"
    assert creator.add_records.call_count == 1
    creator.delete_records.assert_not_called()


@pytest.mark.parametrize("failure", ["network", "missing", "truncated", "duplicate_id", "request_code"])
def test_uncertain_customer_creates_are_checkpointed_and_never_retried(tmp_path, failure):
    books, creator = sync_clients(2)
    if failure == "network":
        creator.add_records.side_effect = OSError("network lost")
    else:
        result = {"code": 3000, "result": [
            {"code": 3000, "data": {"ID": "a"}}, {"code": 3000, "data": {"ID": "b"}}]}
        if failure == "missing":
            result.pop("result")
        elif failure == "truncated":
            result["result"].pop()
        elif failure == "duplicate_id":
            result["result"][1]["data"]["ID"] = "a"
        else:
            result["code"] = 3001
        creator.add_records.side_effect = None
        creator.add_records.return_value = result
    with pytest.raises((OSError, ReconciliationError)):
        sync_creator_customers(books, creator, sync_config(tmp_path))
    assert checkpoint(tmp_path)["status"] == "FAILED"
    assert creator.add_records.call_count == 1
    creator.delete_records.assert_not_called()


def test_batched_sync_dry_run_has_no_writes(tmp_path):
    books, creator = sync_clients(401)
    result = sync_creator_customers(books, creator, sync_config(tmp_path, dry_run=True))
    assert result["candidate_create_count"] == 401
    assert result["created_count"] == 0
    assert result["status"] == "PREVIEW"
    creator.add_records_bulk.assert_not_called()
    creator.update_records.assert_not_called()
    creator.delete_records.assert_not_called()


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
@pytest.mark.parametrize("result", [{"code": 3001}, {"code": 3000, "result": [{"code": 3001}]}, None])
def test_customer_mutation_response_errors_do_not_count_as_success(tmp_path, operation, result):
    books, creator = sync_clients(1)
    creator.get_all_records.return_value = [
        {"ID": "existing", "Customer_Id": "0", "Customer_Name": "old"},
        {"ID": "orphan", "Customer_Id": "absent"}]
    creator.update_records.return_value = {"code": 3000} if operation == "DELETE" else result
    creator.delete_records.return_value = result
    with pytest.raises(ReconciliationError, match="Unconfirmed Creator " + operation):
        sync_creator_customers(books, creator, sync_config(tmp_path))
    saved = checkpoint(tmp_path)
    assert saved["status"] == "FAILED"
    assert saved["deleted_count"] == 0
    assert saved["updated_count"] == (1 if operation == "DELETE" else 0)
    if operation == "UPDATE":
        creator.delete_records.assert_not_called()


def test_bank_index_matches_full_scan_at_tolerance_boundaries_and_used_ids():
    rng = Random(412)
    start = date(2026, 1, 1)
    rows = [{"transaction_id": str(i), "date": (start + timedelta(days=rng.randrange(20))).isoformat(),
             "amount": str(Decimal(rng.randrange(-1000, 1000)) / 100),
             "reference_number": "MATCH" if i % 2 else "other", "description": "narration match"}
            for i in range(500)]
    rows += [{"transaction_id": "boundary", "date": "2026-01-12", "amount": "-5.50",
              "reference_number": "MATCH"}]
    config = CollectionReconciliationConfig("app", "bank", date_tolerance_days=2,
                                            amount_tolerance=Decimal("0.50"))
    reconciler = CollectionReconciler(MagicMock(), MagicMock(), config)
    index = TransactionIndex(rows, "bank")
    used = {str(i) for i in range(0, 500, 3)}
    for offset in range(20):
        day = start + timedelta(days=offset)
        amount = Decimal("5")
        expected = [row for row in rows if row["transaction_id"] not in used
                    and abs((date.fromisoformat(row["date"]) - day).days) <= 2
                    and abs(abs(Decimal(row["amount"])) - amount) <= Decimal("0.50")]
        actual = index.candidates(day, amount, 2, Decimal("0.50"))
        assert {row.transaction_id for row in actual if row.transaction_id not in used} == {
            row["transaction_id"] for row in expected}
        matched, reason = reconciler._find_transaction(
            {"Payment_Date": day, "Amount": "5", "Reference_Number": "match"}, index, used)
        if len(expected) == 1:
            assert matched is expected[0]
        elif len(expected) > 1:
            assert matched is None and reason.startswith("Multiple")
        else:
            assert matched is None and reason.startswith("No bank")


def test_bank_normalization_work_is_per_transaction_not_per_payment():
    from workflows.collection_reconciliation import transaction_index
    rows = [{"transaction_id": str(i), "date": "2026-01-01", "amount": str(i),
             "reference_number": str(i)} for i in range(1000)]
    books, creator = MagicMock(), MagicMock()
    books.bank_transactions.list_all.return_value = rows
    creator.get_all_records.return_value = [
        {"ID": str(i), "Payment_Date": "2026-01-01", "Amount": str(i),
         "Reference_Number": str(i), "Customer_ID": "customer"} for i in range(100)]
    reconciler = CollectionReconciler(creator, books, CollectionReconciliationConfig("app", "bank"))
    with patch.object(transaction_index, "parse_date", wraps=transaction_index.parse_date) as parse:
        result = reconciler.reconcile_pending()
    assert parse.call_count == 1000
    assert len(result["confirmed"]) == 100
    assert not result["failed"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-1"])
def test_nonfinite_or_negative_matching_tolerance_is_rejected(value):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        CollectionReconciliationConfig("app", "bank", amount_tolerance=Decimal(value))


def test_nonfinite_bank_amount_aborts_index_and_invalid_creator_amount_is_unmatched():
    with pytest.raises(ReconciliationError, match="non-finite amount"):
        TransactionIndex([{"transaction_id": "bad", "date": "2026-01-01", "amount": "NaN"}], "bank")
    reconciler = CollectionReconciler(MagicMock(), MagicMock(), CollectionReconciliationConfig("app", "bank"))
    match, reason = reconciler._find_transaction(
        {"Payment_Date": "2026-01-01", "Amount": "NaN", "Reference_Number": "ref"}, [], set())
    assert match is None and "invalid" in reason


def test_bill_month_index_preserves_posting_dates_source_order_and_partial_ranges():
    bills = [
        {"bill_id": "a", "date": "2025-03-01", "txn_value_date": "2026-01-20"},
        {"bill_id": "b", "date": "2026-01-02", "txn_value_date": "2026-02-01"},
        {"bill_id": "c", "date": "2026-01-01", "txn_value_date": "2026-01-10"},
        {"bill_id": "bad", "date": "invalid"},
    ]
    books = MagicMock()
    verifier = GSTR2Verifier(books, bill_snapshot=bills)
    errors = []
    january = verifier._fetch_books_bills(date(2026, 1, 1), date(2026, 1, 31), errors)
    assert [row["bill_id"] for row in january] == ["a", "c"]
    partial = verifier._fetch_books_bills(date(2026, 1, 15), date(2026, 2, 1), errors)
    assert [row["bill_id"] for row in partial] == ["a", "b"]
    assert not errors
    books.bills.list_all.assert_not_called()


def test_bill_month_index_parses_posting_dates_only_once_for_twelve_months():
    from workflows.gstr2_verification import verifier as module
    bills = [{"bill_id": str(month), "date": f"2026-{month:02d}-01",
              "txn_value_date": f"2026-{month:02d}-02"} for month in range(1, 13)]
    books = MagicMock()
    books.bills.list_all.return_value = bills
    verifier = GSTR2Verifier(books)
    with patch.object(module, "parse_date", wraps=module.parse_date) as parse:
        for month in range(1, 13):
            result = verifier._fetch_books_bills(date(2026, month, 1), date(2026, month, 28), [])
            assert [row["bill_id"] for row in result] == [str(month)]
    # Twelve posting dates at index build, plus twelve selected bill dates.
    assert parse.call_count == 24
    books.bills.list_all.assert_called_once_with()
