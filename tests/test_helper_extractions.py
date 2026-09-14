"""Contracts for helpers shared by workflow implementations."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from zoho.helpers import find_item_by_exact_sku
from workflows.collection_reconciliation.identifiers import identifier, identifiers
from workflows.collection_reconciliation.payments import customer_payment_payload
from workflows.core.exceptions import ReconciliationError
from workflows.core.matching import to_finite_decimal


def test_nested_identifiers_preserve_first_and_all_values():
    payload = {"data": [{"ID": "first"}, {"nested": {"ID": "second"}}]}
    assert identifier(payload, ("ID",)) == "first"
    assert identifiers(payload, ("ID",)) == {"first", "second"}


def test_payment_payload_keeps_optional_fields_distinct():
    common = dict(
        customer_id="customer", payment_mode="banktransfer",
        payment_date=date(2026, 9, 14), amount=Decimal("-12.50"),
        reference_number="ref", description="Creator reconciliation",
        account_id="bank", creator_record_id="record",
    )
    basic = customer_payment_payload(**common)
    reviewed = customer_payment_payload(
        **common, creator_payment_id="payment",
        invoices=[{"invoice_id": "invoice", "amount_applied": 12.5, "extra": True}],
    )
    assert basic["amount"] == 12.5
    assert "invoices" not in basic
    assert basic["custom_fields"] == [{"label": "Creator Record ID", "value": "record"}]
    assert reviewed["invoices"] == [{"invoice_id": "invoice", "amount_applied": 12.5}]
    assert reviewed["custom_fields"][-1] == {"label": "Creator Payment ID", "value": "payment"}


def test_payment_payload_requires_valid_amount_and_date():
    with pytest.raises(ReconciliationError, match="valid payment date and amount"):
        customer_payment_payload(
            customer_id="customer", payment_mode="cash", payment_date=None,
            amount=Decimal("1"), reference_number="", description="",
            account_id="bank", creator_record_id="record",
        )


def test_exact_sku_lookup_is_scoped_and_prefers_active_exact_match():
    inventory = MagicMock()
    inventory.items.list.return_value = {"items": [
        {"sku": "SKU-1", "status": "inactive", "item_id": "old"},
        {"sku": "SKU-12", "status": "active", "item_id": "other"},
        {"sku": "sku-1", "status": "active", "item_id": "active"},
    ]}
    assert find_item_by_exact_sku(inventory, "SKU-1", "account")["item_id"] == "active"
    inventory.items.list.assert_called_once_with(
        params={"sku": "SKU-1", "purchase_account_id": "account"}
    )


def test_exact_sku_lookup_rejects_missing_account_before_api_call():
    inventory = MagicMock()
    with pytest.raises(ValueError, match="purchase_account_id"):
        find_item_by_exact_sku(inventory, "SKU-1", "")
    inventory.items.list.assert_not_called()


@pytest.mark.parametrize("value,expected", [
    ("12.50", Decimal("12.50")), ("1,200", None),
    ("NaN", None), (None, None),
])
def test_finite_decimal_preserves_strict_duplicate_payment_parsing(value, expected):
    assert to_finite_decimal(value) == expected
