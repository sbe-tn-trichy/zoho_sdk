import logging
from typing import Dict, Optional

from zoho import HttpTokenProvider
from zoho.books import ZohoBooksAPI
from zoho.wd import ZohoWorkdriveAPI

from .config import Config
from .exceptions import ZohoAuthError

logger = logging.getLogger(__name__)


def fetch_access_tokens(token_url: str = Config.TOKEN_URL) -> Dict[str, Optional[str]]:
    """Retrieve runtime-only access tokens from the configured token broker."""
    logger.info("Retrieving access tokens from configured token service.")
    try:
        tokens = HttpTokenProvider(token_url).get_tokens()
        return {
            service: tokens.get(service)
            for service in ("books", "workdrive", "inventory")
        }
    except Exception as exc:
        logger.error("Failed to fetch access tokens: %s", exc)
        raise ZohoAuthError(
            "Failed to fetch access tokens from the configured token service."
        ) from exc


def get_books_client(
    token: Optional[str] = None,
    org_id: str = Config.ORG_ID,
    domain: str = Config.DOMAIN,
) -> ZohoBooksAPI:
    """Create an authenticated Zoho Books client."""
    if not token:
        token = fetch_access_tokens().get("books")
    if not token:
        raise ZohoAuthError("No Zoho Books access token available.")
    return ZohoBooksAPI(
        access_token=token,
        organization_id=org_id,
        domain=domain,
    )


def get_workdrive_client(
    token: Optional[str] = None,
    domain: str = Config.DOMAIN,
) -> ZohoWorkdriveAPI:
    """Create an authenticated Zoho WorkDrive client."""
    if not token:
        token = fetch_access_tokens().get("workdrive")
    if not token:
        raise ZohoAuthError("No Zoho WorkDrive access token available.")
    return ZohoWorkdriveAPI(access_token=token, domain=domain)
