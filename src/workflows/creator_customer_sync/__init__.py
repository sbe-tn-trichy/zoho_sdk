from typing import Any, Dict

from .config import CreatorCustomerSyncConfig
from .syncer import CreatorCustomerSyncer


def sync_creator_customers(
    books_client: Any,
    creator_client: Any,
    config: CreatorCustomerSyncConfig,
) -> Dict[str, Any]:
    """Convenience helper function to run Creator customer record sync."""
    syncer = CreatorCustomerSyncer(
        books_client=books_client,
        creator_client=creator_client,
        config=config,
    )
    return syncer.execute_sync()


__all__ = [
    "CreatorCustomerSyncConfig",
    "CreatorCustomerSyncer",
    "sync_creator_customers",
]
