"""Regression coverage for the Books/Inventory service boundary."""

from unittest.mock import MagicMock

import pytest

from apps import apply_neoseal_name_updates
from workflows.polycab_rso.processor import _resolve_line_items
from zoho.auth import fetch_token_from_catalyst
from zoho.books import ZohoBooksAPI
from zoho.exceptions import ZohoAuthError
from zoho.helpers.items import fetch_items_by_purchase_account
from zoho.inventory import ZohoInventoryAPI


@pytest.fixture
def http(monkeypatch):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = '{"code": 0}'
    response.json.return_value = {"code": 0}
    request = MagicMock(return_value=response)
    monkeypatch.setattr("requests.request", request)
    return request


@pytest.mark.parametrize("action", ["mark_as_active", "mark_as_inactive"])
def test_item_status_uses_inventory_url_and_token(http, action):
    inventory = ZohoInventoryAPI("inventory-token", "org", domain="in")
    getattr(inventory.items, action)("123")
    call = http.call_args.kwargs
    assert call["url"] == f"https://www.zohoapis.in/inventory/v1/items/123/{action.removeprefix('mark_as_')}"
    assert call["method"] == "POST"
    assert call["headers"]["Authorization"] == "Zoho-oauthtoken inventory-token"
    assert call["params"] == {"organization_id": "org"}


def test_vendor_catalog_paginates_inventory_with_account_and_all_statuses(http):
    inventory = ZohoInventoryAPI("inventory-token", "org")
    http.return_value.json.side_effect = [
        {"items": [{"item_id": "1", "sku": "A"}], "page_context": {"has_more_page": True}},
        {"items": [{"item_id": "2", "sku": "B"}], "page_context": {"has_more_page": False}},
    ]
    result = fetch_items_by_purchase_account(inventory, "account-1")
    assert set(result) == {"A", "B"}
    for page, call in enumerate(http.call_args_list, start=1):
        assert call.kwargs["url"].endswith("/inventory/v1/items")
        assert call.kwargs["params"] == {
            "organization_id": "org", "purchase_account_id": "account-1",
            "filter_by": "Status.All", "page": page, "per_page": 200,
        }


def test_books_no_longer_exposes_item_resource():
    assert not hasattr(ZohoBooksAPI("books-token", "org"), "items")


@pytest.mark.parametrize("account_id", [None, "", "  "])
def test_inventory_vendor_query_refuses_empty_scope(http, account_id):
    with pytest.raises(ValueError, match="purchase_account_id"):
        ZohoInventoryAPI("token", "org").items.list_by_purchase_account(account_id)
    http.assert_not_called()


def test_rso_refuses_empty_scope_before_lookup():
    inventory = MagicMock()
    with pytest.raises(ValueError, match="purchase_account_id"):
        _resolve_line_items(inventory, [{"sku": "SKU"}], "")
    inventory.items.list.assert_not_called()


def test_catalyst_inventory_does_not_fall_back_to_books(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"tokens": {"books": "books-token"}}
    monkeypatch.setattr("requests.post", MagicMock(return_value=response))
    with pytest.raises(ZohoAuthError):
        fetch_token_from_catalyst("https://broker.example/tokens", "inventory")


YAML_ORDER = """inv:
  no: '123'
  date: '2026-09-13'
items:
  - sku: 'SKU'
    name: 'Item'
    qty: 1
    rate: 100
"""


@pytest.mark.parametrize("create_missing", [False, True])
def test_yaml_item_resolution_and_creation_use_inventory(http, create_missing):
    books = ZohoBooksAPI("books-token", "org")
    inventory = ZohoInventoryAPI("inventory-token", "org")
    item = {"item_id": "123", "name": "Item", "sku": "SKU"}
    responses = [{"items": [] if create_missing else [item]}]
    if create_missing:
        responses.append({"item": item})
    responses.append({"salesorder": {"salesorder_id": "456"}})
    http.return_value.json.side_effect = responses
    result = books.sales_orders.create_from_yaml(
        YAML_ORDER, "customer", inventory_client=inventory,
        create_missing_items=create_missing,
        default_accounts={"account_id": "sales", "purchase_account_id": "purchase", "inventory_account_id": "stock"},
    )
    assert result["salesorder"]["salesorder_id"] == "456"
    for call in http.call_args_list[:-1]:
        assert call.kwargs["url"].endswith("/inventory/v1/items")
        assert call.kwargs["headers"]["Authorization"] == "Zoho-oauthtoken inventory-token"
    last = http.call_args.kwargs
    assert last["url"].endswith("/books/v3/salesorders")
    assert last["headers"]["Authorization"] == "Zoho-oauthtoken books-token"
    assert last["json"]["line_items"][0]["item_id"] == "123"


def test_yaml_missing_item_does_not_create_order(http):
    http.return_value.json.return_value = {"items": []}
    with pytest.raises(ValueError, match="not found in Zoho Inventory"):
        ZohoBooksAPI("books-token", "org").sales_orders.create_from_yaml(
            YAML_ORDER, "customer", inventory_client=ZohoInventoryAPI("inventory-token", "org"),
        )
    assert http.call_count == 1
    assert http.call_args.kwargs["method"] == "GET"


@pytest.mark.parametrize("apply", [False, True])
def test_neoseal_updater_constructs_inventory_client(monkeypatch, tmp_path, apply):
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [
        {"item_id": "123", "name": "Solvent 100ml", "sku": "SKU"},
    ]
    factory = MagicMock(return_value=inventory)
    monkeypatch.setattr(apply_neoseal_name_updates, "get_inventory_client", factory)
    args = ["--purchase-account-id", "account-1", "--output-dir", str(tmp_path)]
    if apply:
        args.append("--apply")
    assert apply_neoseal_name_updates.main(args) == 0
    factory.assert_called_once_with()
    inventory.items.list_by_purchase_account.assert_called_once_with("account-1")
    assert inventory.items.update.call_count == int(apply)


def test_neoseal_inventory_update_failure_is_recorded(tmp_path):
    inventory = MagicMock()
    inventory.items.update.side_effect = RuntimeError("Update failed")
    result = apply_neoseal_name_updates.run_plan_or_apply(
        [{"item_id": "123", "name": "Solvent 100ml", "sku": "SKU"}],
        apply=True, client=inventory, output_dir=tmp_path,
    )
    assert result["failure_count"] == 1
    assert result["records"][0]["status"] == "failed"
