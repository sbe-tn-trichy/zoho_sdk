import time
import requests
from typing import Optional

class ZohoOAuth2Manager:
    """
    Handles Zoho OAuth 2.0 access token caching, expiration checks, 
    and token refreshing.
    """
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: Optional[str] = None,
        domain: str = "com",
        access_token: Optional[str] = None,
        expires_at: Optional[float] = None,
        keyring_service: Optional[str] = None,
        keyring_username: Optional[str] = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.domain = domain
        self._access_token = access_token
        self._expires_at = expires_at or 0.0
        self.keyring_service = keyring_service
        self.keyring_username = keyring_username
        self._refresh_token = refresh_token

    @property
    def refresh_token(self) -> str:
        """
        Retrieves the refresh token. Either returns the direct token string 
        or fetches it from the system keyring if keyring parameters are set.
        """
        if self._refresh_token:
            return self._refresh_token
        if self.keyring_service and self.keyring_username:
            try:
                import keyring
                token = keyring.get_password(self.keyring_service, self.keyring_username)
                if not token:
                    raise ValueError(f"No token found in keyring for service '{self.keyring_service}' and username '{self.keyring_username}'")
                return token
            except ImportError as e:
                raise ImportError(
                    "The 'keyring' library is required to retrieve the refresh token from the system keyring. "
                    "Install it using 'pip install keyring'."
                ) from e
        raise ValueError("Must provide either 'refresh_token' or both 'keyring_service' and 'keyring_username' parameters.")

    def get_token_url(self) -> str:
        return f"https://accounts.zoho.{self.domain}/oauth/v2/token"

    def refresh_access_token(self) -> str:
        """
        Calls Zoho's OAuth endpoint to exchange the refresh token for a new access token.
        """
        payload = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(self.get_token_url(), data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "access_token" not in data:
            raise ValueError(f"Failed to refresh access token, response: {data}")
            
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        # Store expiration time with a 60-second buffer
        self._expires_at = time.time() + expires_in - 60
        return self._access_token

    def get_access_token(self) -> str:
        """
        Returns a valid access token. Refreshes automatically if expired or missing.
        """
        if not self._access_token or time.time() >= self._expires_at:
            return self.refresh_access_token()
        return self._access_token


def fetch_token_from_catalyst(url: str, service_key: str) -> Optional[str]:
    """
    Fetches the OAuth token for a specific service from the local Catalyst token endpoint.
    """
    try:
        response = requests.post(url, headers={"Content-Type": "application/json"}, json={}, timeout=10)
        response.raise_for_status()
        res_data = response.json()
        
        # Extract tokens dictionary
        tokens = res_data.get("tokens")
        if not isinstance(tokens, dict):
            # In case it is double-wrapped in body
            body = res_data.get("body")
            if isinstance(body, str):
                import json
                try:
                    body = json.loads(body)
                except Exception:
                    body = {}
            if isinstance(body, dict):
                tokens = body.get("tokens")
                
        if isinstance(tokens, dict):
            # Fallback for inventory to books
            if service_key == "inventory" and "inventory" not in tokens:
                return tokens.get("books")
            return tokens.get(service_key)
            
        return None
    except Exception:
        return None


class CatalystAuth(str):
    """
    Dynamic authentication wrapper that behaves like a string.
    Allows explicit request mutation token switching via get_token_for_request(is_mutation).
    """
    def __new__(cls, direct_token: str, catalyst_token_url: str, service_key: str):
        obj = str.__new__(cls, direct_token)
        obj.direct_token = direct_token
        obj.catalyst_token_url = catalyst_token_url
        obj.service_key = service_key
        return obj

    def get_token_for_request(self, is_mutation: bool) -> str:
        """
        Explicitly resolves token based on request mutation flag,
        bypassing expensive stack introspection.
        """
        if is_mutation and self.catalyst_token_url:
            token = fetch_token_from_catalyst(self.catalyst_token_url, self.service_key)
            if token:
                return token
        return self.direct_token

    def __str__(self) -> str:
        # Default string conversion returns the direct token to avoid unexpected Catalyst triggers
        return self.direct_token


