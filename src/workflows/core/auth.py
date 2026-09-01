from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from zoho import HttpTokenProvider
from zoho.analytics import ZohoAnalyticsAPI
from zoho.books import ZohoBooksAPI
from zoho.creator import ZohoCreatorAPI
from zoho.wd import ZohoWorkdriveAPI

from .config import Config
from .exceptions import ZohoAuthError

logger = logging.getLogger(__name__)


def fetch_access_tokens(token_url: str = Config.TOKEN_URL) -> Dict[str, Optional[str]]:
    """Retrieve runtime-only access tokens from the configured token broker."""
    logger.info("Retrieving access tokens from configured token service.")
    try:
        tokens = HttpTokenProvider(token_url, timeout=30).get_tokens()
        return {
            service: tokens.get(service)
            for service in ("books", "workdrive", "inventory", "creator", "analytics")
        }
    except Exception as exc:
        logger.error("Failed to fetch access tokens: %s", exc)
        raise ZohoAuthError(
            "Failed to fetch access tokens from the configured token service."
        ) from exc


def get_token_for(service_key: str, fallback_key: str = "", token_url: str = Config.TOKEN_URL) -> str:
    """Helper to fetch a fresh token with fallback for a given service."""
    try:
        tokens = HttpTokenProvider(token_url, timeout=30).get_tokens()
        return tokens.get(service_key) or (tokens.get(fallback_key) if fallback_key else "") or ""
    except Exception:
        return ""


def get_books_client(
    token: Optional[str] = None,
    org_id: str = Config.ORG_ID,
    domain: str = Config.DOMAIN,
    token_url: str = Config.TOKEN_URL,
    token_refresh_callback: Optional[Callable[[], str]] = None,
) -> ZohoBooksAPI:
    """Create an authenticated Zoho Books client with token refresh support."""
    if not token:
        token = get_token_for("books", "zoho_books_conn", token_url=token_url)
    if not token:
        raise ZohoAuthError("No Zoho Books access token available.")
    refresh_cb = token_refresh_callback or (lambda: get_token_for("books", "zoho_books_conn", token_url=token_url))
    return ZohoBooksAPI(
        access_token=token,
        organization_id=org_id,
        domain=domain,
        token_refresh_callback=refresh_cb,
    )


def get_creator_client(
    token: Optional[str] = None,
    owner_name: str = "bharathdst",
    domain: str = Config.DOMAIN,
    token_url: str = Config.TOKEN_URL,
    token_refresh_callback: Optional[Callable[[], str]] = None,
) -> ZohoCreatorAPI:
    """Create an authenticated Zoho Creator client with token refresh support."""
    if not token:
        token = get_token_for("creator", "zoho_creator_conn", token_url=token_url)
    if not token:
        raise ZohoAuthError("No Zoho Creator access token available.")
    refresh_cb = token_refresh_callback or (lambda: get_token_for("creator", "zoho_creator_conn", token_url=token_url))
    return ZohoCreatorAPI(
        access_token=token,
        account_owner_name=owner_name,
        domain=domain,
        send_environment_header=False,
        token_refresh_callback=refresh_cb,
    )


def get_analytics_client(
    token: Optional[str] = None,
    org_id: str = Config.ORG_ID,
    domain: str = Config.DOMAIN,
    token_url: str = Config.TOKEN_URL,
    token_refresh_callback: Optional[Callable[[], str]] = None,
) -> ZohoAnalyticsAPI:
    """Create an authenticated Zoho Analytics client with token refresh support."""
    if not token:
        token = get_token_for("analytics", "zoho_analytics_conn", token_url=token_url)
    if not token:
        raise ZohoAuthError("No Zoho Analytics access token available.")
    refresh_cb = token_refresh_callback or (lambda: get_token_for("analytics", "zoho_analytics_conn", token_url=token_url))
    return ZohoAnalyticsAPI(
        access_token=token,
        organization_id=org_id,
        domain=domain,
        token_refresh_callback=refresh_cb,
    )


def get_workdrive_client(
    token: Optional[str] = None,
    domain: str = Config.DOMAIN,
    token_url: str = Config.TOKEN_URL,
) -> ZohoWorkdriveAPI:
    """Create an authenticated Zoho WorkDrive client."""
    if not token:
        token = get_token_for("workdrive", "zoho_workdrive_conn", token_url=token_url)
    if not token:
        raise ZohoAuthError("No Zoho WorkDrive access token available.")
    return ZohoWorkdriveAPI(access_token=token, domain=domain)
