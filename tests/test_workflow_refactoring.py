from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import pytest

from workflows.core.dates import get_fy_date_range
from workflows.core.matching import parse_date
from workflows.core.sequences import analyze_number_series
from workflows.customer_validation import CustomerValidator
from workflows.payment_inspection import extract_series_info, fetch_customer_payments
from workflows.payment_renumbering import build_renumber_plan, execute_renumbering, RenumberingError
from workflows.sales_order_import import create_sales_order_from_yaml, parse_invoice_yaml, SalesOrderImportError
from zoho.books import ZohoBooksAPI
from zoho.exceptions import ZohoBooksError
from zoho.helpers.sequences import parse_doc_number


@pytest.mark.parametrize("value", ["25-26", "2025-26", "2025-2026", "25/26", "2025/2026", "2526", "2025"])
def test_fy_forms(value):
    assert get_fy_date_range(value) == (date(2025, 4, 1), date(2026, 3, 31), "2025-26")


@pytest.mark.parametrize("value", ["bad", "2025-27", "25-2027", "2426", "1899", "99-00", "2099-2100"])
def test_fy_invalid(value):
    with pytest.raises(ValueError):
        get_fy_date_range(value)


def test_fy_boundaries_and_leap_year():
    assert get_fy_date_range("current", date(2024, 3, 31))[0] == date(2023, 4, 1)
    start, end, _ = get_fy_date_range("last", date(2024, 4, 1))
    assert start <= date(2024, 2, 29) <= end
    assert get_fy_date_range("current", date(2024, 4, 1))[0] == date(2024, 4, 1)
    assert get_fy_date_range("previous", date(2025, 1, 1))[0] == date(2023, 4, 1)


@pytest.mark.parametrize("value", ["2025-04-01 12:00:00", "2025-04-01 12:00:00.123", "01/04/2025", "2025-04-01T12:00:00"])
def test_calendar_dates_accept_analytics_timestamps(value):
    assert parse_date(value) == date(2025, 4, 1)


def test_series_sparse_duplicates_widths_and_zero():
    rows = [{"number": value} for value in ["INV-000", "INV-001", "INV-1", "INV-1000000000"]]
    row = analyze_number_series(rows, "number", "date", max_intervals=1)[0]
    assert row["duplicate_suffixes"] == [1]
    assert row["widths"] == [1, 3, 10]
    assert row["missing_count"] == 999999998
    assert row["missing_intervals"] == [(2, 999999999)]
    assert parse_doc_number("2026/001") == ("2026/", 1, 3)
    assert parse_doc_number("0") == ("", 0, 1)
    assert parse_doc_number("text") == ("text", 0, 0)
    assert analyze_number_series([], "n", "d") == []
    row = analyze_number_series([{"n": f"X-{v}"} for v in [1, 3, 5]], "n", "d", max_intervals=1)[0]
    assert row["intervals_truncated"] and row["missing_count"] == 2


def test_inspection_filters_and_queries():
    analytics = Mock()
    analytics.queries.execute.return_value = []
    assert fetch_customer_payments(analytics, "workspace") == []
    assert analytics.queries.execute.call_args.kwargs["workspace_id"] == "workspace"
    records = [{"Payment Number": "X-001", "Payment Date": "01/04/2025"},
               {"Payment Number": "X-003", "Payment Date": "bad"},
               {"Payment Number": "", "Payment Date": "2025-04-02"}]
    summary, count = extract_series_info(records, date(2025, 4, 1), date(2026, 3, 31))
    assert count == 2
    assert {r["series_prefix"] for r in summary} == {"X-", "[EMPTY]"}
    analytics.queries.execute.side_effect = RuntimeError("query failed")
    with pytest.raises(RuntimeError):
        fetch_customer_payments(analytics, "workspace")


def payment(payment_id="p", number="OLD-001"):
    return {"payment_id": payment_id, "payment_number": number, "date": "2025-04-01",
            "amount": 100, "account_id": "bank", "location_id": "location", "customer_id": "customer",
            "invoices": [{"invoice_id": "invoice", "amount_applied": 100}]}


def payment_setup():
    books = Mock()
    state = {"p": payment()}
    books.customer_payments.get.side_effect = lambda key: {"payment": deepcopy(state[key])}
    books.customer_payments.list_all.return_value = [{"payment_id": "existing", "payment_number": "NEW-00002"}]
    def update(key, payload):
        state[key]["payment_number"] = payload["payment_number_prefix"] + payload["payment_number_suffix"]
        return {"code": 0}
    books.customer_payments.update_with_number_series.side_effect = update
    records = [{"Payment ID": "p", "Payment Number": "OLD-001", "Payment Date": "2025-04-01"}]
    plan = build_renumber_plan(books, records, source_prefix="OLD-", destination_prefix="NEW-",
                              start_date=date(2025, 4, 1), end_date=date(2026, 3, 31))
    return books, state, records, plan


def test_renumber_live_max_dry_run_and_verified_execution():
    books, state, _, plan = payment_setup()
    assert plan[0]["new_payment_number"] == "NEW-00003"
    assert execute_renumbering(books, plan)[0]["status"] == "planned"
    books.customer_payments.update_with_number_series.assert_not_called()
    checkpoints = []
    result = execute_renumbering(books, plan, execute=True, checkpoint=checkpoints.append)
    assert result[0]["status"] == "verified"
    assert checkpoints[0][0]["status"] == "submitted"
    assert state["p"]["location_id"] == "location"
    books.customer_payments.update_with_number_series.reset_mock()
    assert execute_renumbering(books, plan, execute=True, previous_results=result, checkpoint=checkpoints.append)[0]["status"] == "verified"
    books.customer_payments.update_with_number_series.assert_not_called()


@pytest.mark.parametrize("change", ["amount", "account_id", "location_id", "customer_id", "date", "payment_number"])
def test_renumber_stale_source_rejected(change):
    books, state, _, plan = payment_setup()
    state["p"][change] = "200" if change == "amount" else "changed"
    with pytest.raises(RenumberingError):
        execute_renumbering(books, plan, execute=True, checkpoint=Mock())
    books.customer_payments.update_with_number_series.assert_not_called()


def test_renumber_collisions_and_invalid_plan():
    books, _, _, plan = payment_setup()
    books.customer_payments.list_all.return_value.append({"payment_id": "other", "payment_number": "NEW-3"})
    with pytest.raises(RenumberingError, match="occupied"):
        execute_renumbering(books, plan)
    with pytest.raises(RenumberingError, match="Duplicate"):
        execute_renumbering(books, plan * 2)
    with pytest.raises(RenumberingError, match="checkpoint"):
        execute_renumbering(books, plan, execute=True)


def test_renumber_timeout_is_checkpointed_and_resumable_after_live_confirmation():
    books, state, _, plan = payment_setup()
    def uncertain(key, payload):
        state[key]["payment_number"] = plan[0]["new_payment_number"]
        raise TimeoutError("unknown outcome")
    books.customer_payments.update_with_number_series.side_effect = uncertain
    checkpoints = []
    result = execute_renumbering(books, plan, execute=True, checkpoint=checkpoints.append)
    assert result[0]["status"] == "failed" and "unknown outcome" in result[0]["error"]
    assert execute_renumbering(books, plan, previous_results=result)[0]["status"] == "verified"
    assert books.customer_payments.update_with_number_series.call_count == 1


@pytest.mark.parametrize("response", [{"code": 1, "message": "rejected"}, {"code": 0}])
def test_renumber_rejection_or_readback_mismatch(response):
    books, _, _, plan = payment_setup()
    books.customer_payments.update_with_number_series.side_effect = None
    books.customer_payments.update_with_number_series.return_value = response
    result = execute_renumbering(books, plan, execute=True, checkpoint=Mock())
    assert result[0]["status"] == "failed"


def test_renumber_discovery_duplicates_empty_and_stale():
    books, _, records, _ = payment_setup()
    kwargs = dict(source_prefix="OLD-", destination_prefix="NEW-", start_date=date(2025, 4, 1), end_date=date(2026, 3, 31))
    assert build_renumber_plan(books, [], **kwargs) == []
    with pytest.raises(RenumberingError, match="duplicate"):
        build_renumber_plan(books, records * 2, **kwargs)
    with pytest.raises(RenumberingError, match="stale"):
        build_renumber_plan(books, records, starting_sequence=2, **kwargs)
    records[0]["Payment Number"] = "OLD-002"
    with pytest.raises(RenumberingError, match="differs"):
        build_renumber_plan(books, records, **kwargs)


ORDER = "inv:\n no: '123'\n date: '01.04.2025'\nitems:\n - sku: 'SKU'\n   name: 'Fan'\n   qty: 1\n   rate: 100\n"


@pytest.mark.parametrize("old,new", [("qty: 1", "qty: NaN"), ("rate: 100", "rate: Infinity"),
                                         ("qty: 1", "qty: 0"), ("name: 'Fan'", "name:"),
                                         ("no: '123'", "number:"), ("01.04.2025", "invalid")])
def test_invalid_invoice_rejected_before_calls(old, new):
    books, inventory = Mock(), Mock()
    with pytest.raises(ValueError):
        create_sales_order_from_yaml(books, ORDER.replace(old, new), "customer", inventory_client=inventory)
    assert not books.mock_calls and not inventory.mock_calls


def test_yaml_legacy_false_key_and_flat_items():
    assert parse_invoice_yaml(ORDER.replace("no:", "False:").replace(" - sku:", " sku:" )).date == "2025-04-01"


def test_yaml_exact_sku_scope_and_fallback():
    books, inventory = Mock(), Mock()
    inventory.items.list.return_value = {"items": [{"sku": "SKU", "item_id": "item", "name": "Fan"}]}
    books.sales_orders.create.side_effect = [ZohoBooksError("number", error_code=4097), {"code": 0, "salesorder": {}}]
    create_sales_order_from_yaml(books, ORDER, "customer", inventory_client=inventory, purchase_account_id="purchase")
    inventory.items.list.assert_called_once_with(params={"sku": "SKU", "purchase_account_id": "purchase"})
    assert "salesorder_number" not in books.sales_orders.create.call_args.args[0]
    inventory.items.list.return_value = {"items": [{"sku": "SKU-OTHER", "item_id": "wrong"}]}
    with pytest.raises(ValueError, match="not found"):
        create_sales_order_from_yaml(books, ORDER, "customer", inventory_client=inventory)


def test_yaml_partial_item_creation_exposes_ids():
    books, inventory = Mock(), Mock()
    inventory.items.list.return_value = {"items": []}
    inventory.items.create.return_value = {"item": {"item_id": "created", "sku": "SKU"}}
    books.sales_orders.create.side_effect = RuntimeError("order failed")
    with pytest.raises(SalesOrderImportError) as error:
        create_sales_order_from_yaml(books, ORDER, "customer", inventory_client=inventory,
                                     create_missing_items=True, default_accounts={"account_id": "sales", "purchase_account_id": "purchase", "inventory_account_id": "stock"})
    assert error.value.created_item_ids == ("created",)
    inventory.items.delete.assert_not_called()


def test_customer_validation_pure_and_fetch_failures():
    assert CustomerValidator().validate_records([])["processed_count"] == 0
    with pytest.raises(ValueError, match="client"):
        CustomerValidator().validate_customer_data()
    books = Mock()
    books.contacts.list_all.return_value = [{"contact_id": "c", "contact_type": "customer"}, {"contact_id": "v", "contact_type": "vendor"}]
    books.contacts.get.side_effect = RuntimeError("unavailable")
    result = CustomerValidator(books).validate_customer_data()
    assert result["failed_contact_ids"] == ["c"]
    assert result["selected_count"] == 1 and result["processed_count"] == 0
    assert not hasattr(ZohoBooksAPI("token", "org"), "customer_validator")
    assert not hasattr(ZohoBooksAPI("token", "org").sales_orders, "create_from_yaml")


def test_blank_numeric_only_and_literal_sentinel_are_distinct():
    records = [{"Payment Number": number} for number in ["", "001", "[EMPTY]"]]
    summaries, count = extract_series_info(records)
    assert count == 3 and len(summaries) == 3
    assert sorted(row["count"] for row in summaries) == [1, 1, 1]
    assert {row["kind"] for row in analyze_number_series(records, "Payment Number", "Payment Date")} == {"empty", "numeric", "nonnumeric"}


def test_multibatch_failure_retains_pending_rows_and_stops():
    books, state, _, plan = payment_setup()
    state["q"] = payment("q", "OLD-002")
    other = deepcopy(plan[0])
    other.update(payment_id="q", current_payment_number="OLD-002", new_payment_number="NEW-00004", suffix="00004")
    plan.append(other)
    books.customer_payments.update_with_number_series.side_effect = RuntimeError("failed")
    checkpoints = []
    results = execute_renumbering(books, plan, execute=True, checkpoint=checkpoints.append)
    assert [r["status"] for r in results] == ["failed", "planned"]
    assert books.customer_payments.update_with_number_series.call_count == 1
    assert len(checkpoints[-1]) == 2


def test_batch_preflight_checks_later_rows_before_first_mutation():
    books, state, _, plan = payment_setup()
    state["q"] = payment("q", "OLD-002")
    other = deepcopy(plan[0])
    other.update(payment_id="q", current_payment_number="OLD-002", new_payment_number="NEW-00004", suffix="00004")
    state["q"]["amount"] = 200
    with pytest.raises(RenumberingError, match="Financial"):
        execute_renumbering(books, plan + [other], execute=True, checkpoint=Mock())
    books.customer_payments.update_with_number_series.assert_not_called()


def test_previously_verified_payment_cannot_revert_silently():
    books, _, _, plan = payment_setup()
    with pytest.raises(RenumberingError, match="Previously verified"):
        execute_renumbering(books, plan, previous_results=[{"payment_id": "p", "status": "verified", "updated_at": None, "error": None}])


@pytest.mark.parametrize("old,new", [("name: 'Fan'", "name: 'Fan"), ("no: '123'", "no: |"),
                                         ("rate: 100", "rate: 1e9999")])
def test_invoice_unsupported_values_fail_before_network(old, new):
    books, inventory = Mock(), Mock()
    with pytest.raises(ValueError):
        create_sales_order_from_yaml(books, ORDER.replace(old, new), "customer", inventory_client=inventory)
    assert not books.mock_calls and not inventory.mock_calls


def test_customer_missing_or_wrong_detail_identity_is_reported():
    books = Mock()
    books.contacts.list_all.return_value = [{"contact_id": "c", "contact_type": "customer"}]
    books.contacts.get.return_value = {"contact": {"contact_id": "wrong"}}
    result = CustomerValidator(books).validate_customer_data()
    assert result["failed_count"] == 1 and result["processed_count"] == 0
    with pytest.raises(ValueError):
        CustomerValidator(books).validate_customer_data(limit=-1)


def test_renumber_cli_dry_run_resume_and_error_exit(monkeypatch, tmp_path):
    from apps import renumber_sbe2627_payments as app
    books, state, records, plan = payment_setup()
    monkeypatch.setattr(app, "get_books_client", lambda: books)
    monkeypatch.setattr(app, "get_analytics_client", Mock())
    monkeypatch.setattr(app, "get_target_payments", lambda *_: records)
    argv = ["--source-prefix", "OLD-", "--destination-prefix", "NEW-", "--output-dir", str(tmp_path)]
    assert app.main(argv) == 0
    books.customer_payments.update_with_number_series.assert_not_called()
    audit_file = next(tmp_path.glob("*.json"))
    import json
    audit = json.loads(audit_file.read_text())
    assert audit["plan"] == plan and audit["results"][0]["status"] == "planned"
    assert app.main(["--resume", str(audit_file), "--execute"]) == 0
    assert state["p"]["payment_number"] == "NEW-00003"
    books.customer_payments.update_with_number_series.reset_mock()
    assert app.main(["--resume", str(audit_file), "--execute"]) == 0
    books.customer_payments.update_with_number_series.assert_not_called()
    state["p"]["payment_number"] = "OLD-001"
    with pytest.raises(RenumberingError, match="Previously verified"):
        app.main(["--resume", str(audit_file), "--execute"])


def test_inspection_cli_preserves_report_schema(monkeypatch, tmp_path):
    from apps import find_customer_payment_series as app
    import json
    import sys
    analytics = Mock()
    analytics.queries.execute.return_value = [{"Payment Number": "X-001", "Payment Date": "2025-04-01"}]
    monkeypatch.setattr(app, "get_analytics_client", lambda: analytics)
    monkeypatch.setattr(sys, "argv", ["find_customer_payment_series", "--fy", "2025-26", "--output-dir", str(tmp_path)])
    app.main()
    report = json.loads((tmp_path / "customer_payment_series_2025_26.json").read_text())
    assert report["total_period_records"] == 1 and report["total_series"] == 1
    assert report["series"][0]["number_range"] == "001 - 001"
