from typing import Any, Dict

from .config import CreatorCustomerDeleteSyncConfig
from .syncer import CreatorCustomerDeleteSyncer


def sync_creator_customer_deletions(
    books_client: Any,
    creator_client: Any,
    config: CreatorCustomerDeleteSyncConfig,
) -> Dict[str, Any]:
    """Convenience helper function to run Creator customer record deletion sync."""
    syncer = CreatorCustomerDeleteSyncer(
        books_client=books_client,
        creator_client=creator_client,
        config=config,
    )
    return syncer.execute_sync()


__all__ = [
    "CreatorCustomerDeleteSyncConfig",
    "CreatorCustomerDeleteSyncer",
    "sync_creator_customer_deletions",
]
