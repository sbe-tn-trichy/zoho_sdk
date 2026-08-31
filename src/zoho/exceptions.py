from typing import Any, Optional, Union


class ZohoError(Exception):
    """Base exception class for all Zoho SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[Union[str, int]] = None,
        response_data: Optional[Any] = None,
        endpoint: Optional[str] = None,
        retry_after: Optional[Union[str, int]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.response_data = response_data
        self.endpoint = endpoint
        self.retry_after = retry_after


class ZohoAuthError(ZohoError):
    """Authentication or token-provider failure."""
    pass

class ZohoAnalyticsError(ZohoError):
    """Zoho Analytics API failure."""
    pass

class ZohoBooksError(ZohoError):
    """Custom exception for Zoho Books API errors."""
    pass

class ZohoInventoryError(ZohoError):
    """Custom exception for Zoho Inventory API errors."""
    pass

class ZohoWorkdriveError(ZohoError):
    """Custom exception for Zoho WorkDrive API errors."""
    pass

class ZohoMailError(ZohoError):
    """Custom exception for Zoho Mail API errors."""
    pass

class ZohoCreatorError(ZohoError):
    """Custom exception for Zoho Creator API errors."""
    pass

class ZohoCliqError(ZohoError):
    """Custom exception for Zoho Cliq API errors."""
    pass

class ZohoSheetError(ZohoError):
    """Custom exception for Zoho Sheet API errors."""
    pass
