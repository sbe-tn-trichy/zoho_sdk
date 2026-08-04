from typing import Any, Dict, Optional

from zoho.auth import HttpTokenProvider
from zoho.base_client import BaseZohoClient

from .metadata import Metadata
from .resources import Queries, Views


class ZohoAnalyticsAPI(BaseZohoClient):
    """Client for Zoho Analytics Data and Bulk Export APIs."""

    def __init__(
        self,
        access_token: str,
        organization_id: str,
        domain: str = "com",
        token_refresh_callback: Optional[Any] = None,
    ):
        if not organization_id:
            raise ValueError("organization_id is required.")
        super().__init__(
            access_token=access_token,
            domain=domain,
            base_url=f"https://analyticsapi.zoho.{domain}/restapi/v2",
            service_name="analytics",
            token_refresh_callback=token_refresh_callback,
            default_timeout=60,
        )
        self.organization_id = organization_id
        self.views = Views(self)
        self.metadata = Metadata(self)
        self.queries = Queries(self)

    @classmethod
    def from_token_provider(
        cls,
        token_url: str = "http://localhost:3000/server/new/tokens",
        organization_id: Optional[str] = None,
        domain: str = "com",
        token_service_key: str = "zoho_analytics_conn",
        token_refresh_callback: Optional[Any] = None,
    ) -> "ZohoAnalyticsAPI":
        """Create a client using an access token from an HTTP token broker."""
        token = HttpTokenProvider(
            token_url,
            fallback_services={"zoho_analytics_conn": "analytics"},
        ).get_token(token_service_key)
        return cls(
            access_token=token,
            organization_id=organization_id or "",
            domain=domain,
            token_refresh_callback=token_refresh_callback,
        )

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        override_url: Optional[str] = None,
    ) -> Any:
        request_headers = {"ZANALYTICS-ORGID": self.organization_id}
        if headers:
            request_headers.update(headers)
        return super().request(
            method=method,
            endpoint=endpoint,
            json=json,
            params=params,
            headers=request_headers,
            override_url=override_url,
        )
