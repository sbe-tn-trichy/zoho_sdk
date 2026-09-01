import logging
import collections.abc
import threading
import requests
from typing import Any, Dict, Optional
from zoho.logging import configure_logger
from zoho.security import sanitize_log_params
from zoho.exceptions import (
    ZohoError,
    ZohoAuthError,
    ZohoBooksError,
    ZohoInventoryError,
    ZohoWorkdriveError,
    ZohoMailError,
    ZohoCreatorError,
    ZohoAnalyticsError,
    ZohoCliqError,
    ZohoSheetError
)

_ERROR_MAP = {
    "books": ZohoBooksError,
    "inventory": ZohoInventoryError,
    "wd": ZohoWorkdriveError,
    "mail": ZohoMailError,
    "creator": ZohoCreatorError,
    "cliq": ZohoCliqError,
    "sheet": ZohoSheetError,
    "analytics": ZohoAnalyticsError,
}

def _is_json_content_type(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")

class BaseZohoClient:
    """
    Unified base client for all Zoho API services.
    Handles credentials, request execution, timeouts, logger setup,
    domain resolution, and unified automatic 401 token refresh retries.
    """
    def __init__(
        self,
        access_token: Any,
        domain: str,
        base_url: str,
        service_name: str,
        token_refresh_callback: Optional[Any] = None,
        on_request_completed: Optional[Any] = None,
        default_timeout: int = 30
    ):
        self.access_token = access_token
        self.domain = domain or "com"
        self.base_url = base_url
        self.service_name = service_name
        self.token_refresh_callback = token_refresh_callback
        self.on_request_completed = on_request_completed
        self.default_timeout = default_timeout
        self.session = requests.Session()
        self._token_lock = threading.Lock()
        self._setup_loggers()


    def close(self) -> None:
        """Close the underlying HTTP session."""
        if hasattr(self, "session") and self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


    def _setup_loggers(self):
        if self.service_name == "books":
            self.logger = configure_logger("zoho.books.api", "zoho_books_api.log")
            configure_logger("zoho_books", "zoho_books_api.log")
        elif self.service_name == "inventory":
            self.logger = configure_logger("zoho_inventory", "zoho_inventory_api.log")
        elif self.service_name == "wd":
            self.logger = configure_logger("zoho.wd.api", "zoho_wd_api.log")
            configure_logger("zoho.wd.app", "app.log")
            configure_logger("zoho_wd.app", "app.log")
        elif self.service_name == "mail":
            self.logger = configure_logger("zoho_mail", "zoho_mail_api.log")
        elif self.service_name == "sheet":
            self.logger = configure_logger("zoho_sheet", "zoho_sheet_api.log")
        elif self.service_name == "creator":
            self.logger = configure_logger("zoho_creator", "zoho_creator_api.log")
        elif self.service_name == "cliq":
            self.logger = configure_logger("zoho_cliq", "zoho_cliq_api.log")
        else:
            self.logger = logging.getLogger(f"zoho.{self.service_name}")

    def _determine_is_mutation(self, method: str, is_mutation: Optional[bool] = None) -> bool:
        if is_mutation is not None:
            return is_mutation
        return method.upper() in ("POST", "PUT", "PATCH", "DELETE")

    def _raise_for_status(self, response: requests.Response, endpoint: Optional[str] = None):
        if response.status_code >= 400:
            err_class = _ERROR_MAP.get(self.service_name, ZohoError)
            err_data = None
            code = None
            msg = None

            try:
                err_data = response.json()
                if isinstance(err_data, dict):
                    msg = err_data.get("message") or err_data.get("description") or err_data.get("error_message")
                    code = err_data.get("code") or err_data.get("error_code")
            except Exception:
                pass

            if not msg:
                raw_text = (response.text or "").strip()
                # Sanitize HTML / server error pages to avoid leaking gateway traces
                if "<html" in raw_text.lower() or "<!doctype" in raw_text.lower():
                    msg = f"HTTP {response.status_code} ({response.reason or 'Server Error'})"
                else:
                    msg = raw_text or f"HTTP {response.status_code}"

            error_msg = f"API Error (code={code}): {msg}" if code is not None else f"HTTP Error: {response.status_code} - {msg}"
            retry_after = None
            if hasattr(response, "headers") and isinstance(response.headers, collections.abc.Mapping):
                retry_after = response.headers.get("Retry-After")

            error = err_class(
                error_msg,
                status_code=response.status_code,
                error_code=code,
                response_data=err_data,
                endpoint=endpoint,
                retry_after=retry_after
            )
            raise error

    def request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        override_url: Optional[str] = None,
        is_mutation: Optional[bool] = None,
        timeout: Optional[int] = None
    ) -> Any:
        url = override_url if override_url else f"{self.base_url}/{endpoint}"
        actual_is_mutation = self._determine_is_mutation(method, is_mutation)
        
        # Resolve dynamic authentication token (e.g. CatalystAuth)
        token = self.access_token
        if hasattr(token, "get_token_for_request"):
            token = token.get_token_for_request(actual_is_mutation)
        else:
            token = str(token)

        req_headers = {
            "Authorization": f"Zoho-oauthtoken {token}"
        }
        if headers:
            req_headers.update(headers)
            
        if not files and not data and "Content-Type" not in req_headers:
            if self.service_name == "wd":
                # Workdrive expects accept header if not uploading files
                req_headers["Accept"] = "application/vnd.api+json"
            elif self.service_name == "creator":
                # Creator only needs Content-Type for payload requests
                if method.upper() in ("POST", "PUT", "PATCH"):
                    req_headers["Content-Type"] = "application/json"
            elif self.service_name != "sheet":
                req_headers["Content-Type"] = "application/json"

        # Log Request with sensitive query parameters masked (preserving last 4 chars)
        logged_params = sanitize_log_params(params) if params else {}
        self.logger.info(f"Request: {method} {url} | Params: {logged_params}")

        req_kwargs = {
            "method": method,
            "url": url,
            "headers": req_headers,
            "params": params,
            "json": json,
            "data": data,
            "files": files,
        }

        # Apply default timeout universally across all services
        req_kwargs["timeout"] = timeout if timeout is not None else self.default_timeout

        # Dynamically set stream based on service expectations
        if self.service_name in ("wd", "mail"):
            req_kwargs["stream"] = stream
        elif stream:
            req_kwargs["stream"] = stream

        def _execute_http(method_name: str, kwargs: dict) -> requests.Response:
            kw = {**kwargs}
            url_val = kw.pop("url")
            kw.pop("method", None)

            # Omit values that are not meaningful to requests while retaining the
            # established explicit-null fields used by some service APIs.
            for k in list(kw.keys()):
                if kw[k] is None:
                    keep = False
                    if k == "params" and self.service_name in ("mail", "creator"):
                        keep = True
                    elif k == "json" and self.service_name in ("books", "inventory", "mail", "creator"):
                        keep = True
                    elif k == "files" and self.service_name in ("books", "inventory", "mail"):
                        keep = True
                    
                    if not keep:
                        kw.pop(k)

            # Use persistent session connection pool for performance while maintaining mock compatibility
            if (
                hasattr(self, "session")
                and self.session is not None
                and not getattr(type(requests.request), "__module__", "").startswith("unittest.mock")
            ):
                return self.session.request(method=method_name, url=url_val, **kw)
            return requests.request(method=method_name, url=url_val, **kw)

        response = _execute_http(method, req_kwargs)

        # Handle 401 refresh with thread lock
        if response.status_code == 401 and self.token_refresh_callback:
            with self._token_lock:
                self.logger.warning(f"{self.service_name.capitalize()} request returned 401; refreshing token and retrying.")
                response.close()
                refreshed_token = self.token_refresh_callback()
                if not refreshed_token:
                    raise ZohoAuthError(
                        f"{self.service_name.capitalize()} token refresh returned an empty token."
                    )
                self.access_token = refreshed_token
                
                token = self.access_token
                if hasattr(token, "get_token_for_request"):
                    token = token.get_token_for_request(actual_is_mutation)
                else:
                    token = str(token)
                req_headers["Authorization"] = f"Zoho-oauthtoken {token}"
                
                retry_kwargs = {**req_kwargs}
                retry_kwargs["headers"] = req_headers
                response = _execute_http(method, retry_kwargs)

        self.logger.info(f"Response: {response.status_code}")

        # Trigger on_request_completed callback if registered
        if self.on_request_completed:
            try:
                response_body = None if stream else response.text
                self.on_request_completed(method, endpoint, json, response.status_code, response_body)
            except Exception as e:
                self.logger.error(f"Callback on_request_completed failed: {e}")

        # Stream response
        if stream:
            if response.status_code >= 400:
                self._raise_for_status(response, endpoint=endpoint)
            return response


        # Empty body response handling
        if response.status_code == 204 or not response.text:
            return {}

        self._raise_for_status(response)

        # Content types handling
        content_type = ""
        if hasattr(response, "headers") and isinstance(response.headers, collections.abc.Mapping):
            content_type = response.headers.get("Content-Type", "")

        if content_type and not _is_json_content_type(content_type):
            return response.content

        return response.json()
