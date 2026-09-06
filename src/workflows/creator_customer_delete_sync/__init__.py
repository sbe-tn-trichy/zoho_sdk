"""Compatibility aliases; these now perform full customer reconciliation."""
from ..creator_customer_sync import (
    CreatorCustomerSyncConfig as CreatorCustomerDeleteSyncConfig,
    CreatorCustomerSyncer as CreatorCustomerDeleteSyncer,
    sync_creator_customers as sync_creator_customer_deletions,
)

__all__ = ["CreatorCustomerDeleteSyncConfig", "CreatorCustomerDeleteSyncer", "sync_creator_customer_deletions"]
