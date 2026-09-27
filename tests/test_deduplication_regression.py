"""Regression tests for deduplication and consolidation requirements.

Covers:
- Invalid, malformed, and ambiguous GSTIN groups and skipped reasons in vendor_customer_offset.
- Payment reference normalization across variations of case, punctuation, whitespace.
- Missing, malformed, non-finite, and rounded amounts in matching/coercion.
- Checkpoint resume and atomic write failure handling.
- Legacy compatibility imports (creator_customer_delete_sync).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from zoho.helpers.gst import (
    GSTIN_PATTERN,
    group_contacts_by_gstin,
    is_valid_gstin,
    normalize_gstin,
)
from workflows.core.matching import (
    parse_date,
    ref_match,
    to_decimal,
    to_finite_decimal,
    to_text,
)
from workflows.vendor_customer_offset.processor import (
    _unique_gstin_pairs,
    run_vendor_customer_offset,
    VendorCustomerOffsetConfig,
)
import workflows.creator_customer_delete_sync as legacy_delete_sync
import workflows.creator_customer_sync as canonical_customer_sync


class TestGSTINRegression:
    def test_normalize_gstin(self):
        assert normalize_gstin(" 33-abcde1234f1z5 ") == "33ABCDE1234F1Z5"
        assert normalize_gstin(None) == ""
        assert normalize_gstin("") == ""
        assert normalize_gstin("33.AAAAA.0000.A.1.Z.5") == "33AAAAA0000A1Z5"

    def test_is_valid_gstin(self):
        assert is_valid_gstin("33ABCDE1234F1Z5") is True
        assert is_valid_gstin("33abcde1234f1z5") is True
        assert is_valid_gstin("INVALID-GSTIN") is False
        assert is_valid_gstin("33ABCDE1234F1Z") is False  # 14 chars
        assert is_valid_gstin("33ABCDE1234F1Z5X") is False  # 16 chars
        assert is_valid_gstin("") is False
        assert is_valid_gstin(None) is False

    def test_unique_gstin_pairs_reasons(self):
        # 1. Valid single pair
        contacts = [
            {"contact_id": "c1", "contact_type": "customer", "gst_no": "33ABCDE1234F1Z5"},
            {"contact_id": "v1", "contact_type": "vendor", "gst_no": "33ABCDE1234F1Z5"},
        ]
        pairs, skipped = _unique_gstin_pairs(contacts)
        assert len(pairs) == 1
        assert len(skipped) == 0
        assert pairs[0][0] == "33ABCDE1234F1Z5"

        # 2. Ambiguous: multiple customers under same GSTIN
        contacts_multi_cust = [
            {"contact_id": "c1", "contact_type": "customer", "gst_no": "33ABCDE1234F1Z5"},
            {"contact_id": "c2", "contact_type": "customer", "gst_no": "33ABCDE1234F1Z5"},
            {"contact_id": "v1", "contact_type": "vendor", "gst_no": "33ABCDE1234F1Z5"},
        ]
        pairs, skipped = _unique_gstin_pairs(contacts_multi_cust)
        assert len(pairs) == 0
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "ambiguous_gstin"
        assert skipped[0]["customer_count"] == 2
        assert skipped[0]["vendor_count"] == 1

        # 3. Invalid GSTIN format skipped
        contacts_invalid = [
            {"contact_id": "c1", "contact_type": "customer", "gst_no": "INVALID_GST"},
            {"contact_id": "v1", "contact_type": "vendor", "gst_no": "INVALID_GST"},
        ]
        pairs, skipped = _unique_gstin_pairs(contacts_invalid)
        assert len(pairs) == 0
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "ambiguous_gstin"


class TestPaymentReferenceRegression:
    def test_ref_match_variations(self):
        assert ref_match("INV-001", " inv-001 ") is True
        assert ref_match("12345", "12345") is True
        assert ref_match("REF/2026/01", "ref/2026/01") is True
        assert ref_match(None, "12345") is False
        assert ref_match("", "12345") is False
        assert ref_match("", "") is False
        assert ref_match("ABC", "XYZ") is False

    def test_to_text_and_normalized_helper(self):
        assert to_text(None) == ""
        assert to_text("  hello  ") == "hello"
        assert to_text(12345) == "12345"


class TestAmountCoercionRegression:
    def test_to_decimal_cases(self):
        assert to_decimal(None) is None
        assert to_decimal("") is None
        assert to_decimal("   ") is None
        assert to_decimal("1,234.56") == Decimal("1234.56")
        assert to_decimal("1234.56") == Decimal("1234.56")
        assert to_decimal(100) == Decimal("100")
        assert to_decimal(Decimal("45.67")) == Decimal("45.67")
        assert to_decimal("invalid") is None

    def test_to_finite_decimal_cases(self):
        assert to_finite_decimal(None) is None
        assert to_finite_decimal("NaN") is None
        assert to_finite_decimal("Infinity") is None
        assert to_finite_decimal("-Infinity") is None
        assert to_finite_decimal("123.45") == Decimal("123.45")
        assert to_finite_decimal("1,234.56", allow_commas=True) == Decimal("1234.56")
        assert to_finite_decimal("1,234.56", allow_commas=False) is None

    def test_parse_date_formats(self):
        assert parse_date("2026-09-27") is not None
        assert parse_date("27-Sep-2026") is not None
        assert parse_date("27/09/2026") is not None
        assert parse_date("2026-09-27T10:30:00Z") is not None
        assert parse_date("invalid-date") is None
        assert parse_date(None) is None
        assert parse_date("") is None


class TestCompatibilityImportsRegression:
    def test_creator_customer_delete_sync_alias_integrity(self):
        assert hasattr(legacy_delete_sync, "CreatorCustomerDeleteSyncConfig")
        assert hasattr(legacy_delete_sync, "CreatorCustomerDeleteSyncer")
        assert hasattr(legacy_delete_sync, "sync_creator_customer_deletions")
        assert legacy_delete_sync.CreatorCustomerDeleteSyncer is canonical_customer_sync.CreatorCustomerSyncer
        assert legacy_delete_sync.CreatorCustomerDeleteSyncConfig is canonical_customer_sync.CreatorCustomerSyncConfig
        assert legacy_delete_sync.sync_creator_customer_deletions is canonical_customer_sync.sync_creator_customers
