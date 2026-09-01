from __future__ import annotations

from typing import Type
from ..base_resource import BaseResource as _BaseResource
from .exceptions import ZohoInventoryError


class BaseResource(_BaseResource):
    """Base class for Zoho Inventory modules providing standard CRUD operations."""

    error_class: Type[ZohoInventoryError] = ZohoInventoryError
    logger_name: str = "zoho.inventory.api"
