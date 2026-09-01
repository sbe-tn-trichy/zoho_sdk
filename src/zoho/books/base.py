from __future__ import annotations

from typing import Type
from ..base_resource import BaseResource as _BaseResource
from .exceptions import ZohoBooksError


class BaseResource(_BaseResource):
    """Base class for Zoho Books modules providing standard CRUD operations."""

    error_class: Type[ZohoBooksError] = ZohoBooksError
    logger_name: str = "zoho.books.api"
