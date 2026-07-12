from typing import Any, Dict, Optional

from zoho.base_client import BaseZohoClient

from .resources import Views


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
