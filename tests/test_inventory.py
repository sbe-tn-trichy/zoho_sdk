import unittest
from unittest.mock import patch, MagicMock
from zoho.inventory import ZohoInventoryAPI
from zoho.inventory.exceptions import ZohoInventoryError
from zoho.inventory.base import BaseResource

class TestZohoInventoryAPI(unittest.TestCase):
    def setUp(self):
        self.access_token = "fake_access_token"
        self.org_id = "org123"
        self.client = ZohoInventoryAPI(access_token=self.access_token, organization_id=self.org_id, domain="com")

    def test_init_success(self):
        self.assertEqual(self.client.access_token, self.access_token)
        self.assertEqual(self.client.organization_id, self.org_id)
        self.assertEqual(self.client.base_url, "https://www.zohoapis.com/inventory/v1")
        self.assertIsNotNone(self.client.item_groups)

    def test_init_missing_org(self):
        with self.assertRaises(ValueError):
            ZohoInventoryAPI(access_token=self.access_token, organization_id="")

    @patch("requests.request")
    def test_request_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}
        mock_request.return_value = mock_response

        res = self.client.request("GET", "items")
        self.assertEqual(res, {"status": "ok"})
        mock_request.assert_called_once_with(
            method="GET",
            url="https://www.zohoapis.com/inventory/v1/items",
            headers={
                "Authorization": "Zoho-oauthtoken fake_access_token",
                "Content-Type": "application/json"
            },
            params={"organization_id": "org123"},
            json=None,
            files=None,
            timeout=30
        )

    @patch("requests.request")
    def test_request_token_refresh(self, mock_request):
        token_callback = MagicMock(return_value="new_token")
        client = ZohoInventoryAPI(access_token="old_token", organization_id="org123", token_refresh_callback=token_callback)
        
        mock_response1 = MagicMock()
        mock_response1.status_code = 401
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.text = '{"status": "ok"}'
        mock_response2.json.return_value = {"status": "ok"}
        
        mock_request.side_effect = [mock_response1, mock_response2]

        res = client.request("GET", "items")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(client.access_token, "new_token")
        self.assertEqual(mock_request.call_count, 2)


class TestInventoryBaseResource(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.resource = BaseResource(self.client, "testresource")
        self.resource.required_fields = ["name", "code"]
        self.resource.defaults = {"status": "active"}
        self.resource.line_item_required_fields = ["item_id", "qty"]
        self.resource.line_item_defaults = {"rate": 0.0}

    def test_prepare_payload_create_success(self):
        data = {
            "name": "Widget",
            "code": "W1",
            "line_items": [{"item_id": "i1", "qty": 5}]
        }
        payload = self.resource._prepare_payload(data, check_required=True)
        self.assertEqual(payload["name"], "Widget")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["line_items"][0]["rate"], 0.0)

    def test_prepare_payload_create_missing_field(self):
        data = {"name": "Widget"} # missing code
        with self.assertRaises(ZohoInventoryError):
            self.resource._prepare_payload(data, check_required=True)

    def test_prepare_payload_create_missing_line_field(self):
        data = {
            "name": "Widget",
            "code": "W1",
            "line_items": [{"item_id": "i1"}] # missing qty
        }
        with self.assertRaises(ZohoInventoryError):
            self.resource._prepare_payload(data, check_required=True)

    def test_prepare_payload_update(self):
        data = {"name": "Updated Widget"}
        payload = self.resource._prepare_payload(data, check_required=False)
        self.assertEqual(payload, data) # no defaults merged, no required checks

    def test_list(self):
        self.resource.list(params={"custom": "val"})
        self.client.request.assert_called_once_with('GET', 'testresource', params={"custom": "val"})

    def test_list_all(self):
        page1 = {"testresource": [{"id": "r1"}], "page_context": {"has_more_page": True}}
        page2 = {"testresource": [{"id": "r2"}], "page_context": {"has_more_page": False}}
        self.client.request.side_effect = [page1, page2]

        records = self.resource.list_all()
        self.assertEqual(records, [{"id": "r1"}, {"id": "r2"}])
        self.assertEqual(self.client.request.call_count, 2)

    def test_get(self):
        self.resource.get("r123", params={"p": "1"})
        self.client.request.assert_called_once_with('GET', 'testresource/r123', params={"p": "1"})

    def test_create(self):
        data = {"name": "Widget", "code": "W1"}
        self.resource.create(data)
        self.client.request.assert_called_once_with(
            'POST', 'testresource', json={"name": "Widget", "code": "W1", "status": "active"}, params=None, files=None
        )

    def test_update(self):
        data = {"name": "Widget"}
        self.resource.update("r123", data)
        self.client.request.assert_called_once_with(
            'PUT', 'testresource/r123', json={"name": "Widget"}, params=None, files=None
        )

    def test_delete(self):
        self.resource.delete("r123")
        self.client.request.assert_called_once_with('DELETE', 'testresource/r123', params=None)


class TestMoveOrders(unittest.TestCase):
    def test_actions(self):
        client = MagicMock()
        from zoho.inventory.resources.move_orders import MoveOrders
        move_orders = MoveOrders(client)
        
        move_orders.mark_as_confirmed("m123")
        client.request.assert_any_call('POST', 'moveorders/m123/status/confirmed', json=None, params=None)
        
        move_orders.mark_as_in_progress("m123")
        client.request.assert_any_call('POST', 'moveorders/m123/status/inprogress', json=None, params=None)

        move_orders.mark_as_completed("m123")
        client.request.assert_any_call('POST', 'moveorders/m123/status/completed', json=None, params=None)


class TestTransferOrders(unittest.TestCase):
    def test_actions(self):
        client = MagicMock()
        from zoho.inventory.resources.transfer_orders import TransferOrders
        to = TransferOrders(client)

        to.mark_as_in_transit("t123")
        client.request.assert_any_call('POST', 'transferorders/t123/status/intransit', json=None, params=None)

        to.mark_as_received("t123")
        client.request.assert_any_call('POST', 'transferorders/t123/status/received', json=None, params=None)

        to.submit_for_approval("t123")
        client.request.assert_any_call('POST', 'transferorders/t123/submit', json=None, params=None)

        to.approve("t123")
        client.request.assert_any_call('POST', 'transferorders/t123/approve', json=None, params=None)

        to.reject("t123")
        client.request.assert_any_call('POST', 'transferorders/t123/reject', json=None, params=None)


class TestItemGroups(unittest.TestCase):
    def test_actions(self):
        client = MagicMock()
        from zoho.inventory.resources.item_groups import ItemGroups
        ig = ItemGroups(client)

        ig.mark_as_active("ig123")
        client.request.assert_any_call('POST', 'itemgroups/ig123/active', json=None, params=None)

        ig.mark_as_inactive("ig123")
        client.request.assert_any_call('POST', 'itemgroups/ig123/inactive', json=None, params=None)


class TestInventoryCatalystAuth(unittest.TestCase):
    @patch("requests.request")
    @patch("requests.post")
    def test_catalyst_auth_put_and_delete(self, mock_post, mock_request):
        mock_response_catalyst = MagicMock()
        mock_response_catalyst.status_code = 200
        # In Zoho Inventory, the key used is "books" as fallback
        mock_response_catalyst.json.return_value = {
            "status": "success",
            "tokens": {"books": "catalyst_inventory_books_token"}
        }
        mock_post.return_value = mock_response_catalyst

        mock_response_zoho = MagicMock()
        mock_response_zoho.status_code = 200
        mock_response_zoho.json.return_value = {"status": "ok"}
        mock_response_zoho.text = '{"status": "ok"}'
        mock_request.return_value = mock_response_zoho

        from zoho.auth import CatalystAuth
        auth = CatalystAuth(
            direct_token="direct_token",
            catalyst_token_url="http://localhost:3000/server/new/tokens",
            service_key="inventory"
        )
        client = ZohoInventoryAPI(
            access_token=auth,
            organization_id="org123"
        )

        client.request("GET", "items")
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        mock_request.reset_mock()
        client.request("POST", "items", json={})
        mock_post.assert_not_called()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken direct_token")

        mock_request.reset_mock()
        client.request("PUT", "items/item123", json={})
        mock_post.assert_called_once_with(
            "http://localhost:3000/server/new/tokens",
            headers={"Content-Type": "application/json"},
            json={},
            timeout=10
        )
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_inventory_books_token")

        mock_request.reset_mock()
        mock_post.reset_mock()
        client.request("DELETE", "items/item123")
        mock_post.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"]["Authorization"], "Zoho-oauthtoken catalyst_inventory_books_token")


if __name__ == "__main__":
    unittest.main()
