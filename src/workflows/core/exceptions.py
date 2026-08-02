class ZohoUsableError(Exception):
    """Base exception class for all errors in the workflows library."""
    pass

class ZohoAuthError(ZohoUsableError, ValueError):
    """Raised when authentication with Zoho Book or WorkDrive fails, or client configuration is invalid."""
    pass

class LedgerParsingError(ZohoUsableError, ValueError):
    """Raised when reading, parsing, or normalizing vendor ledgers or bank statements fails."""
    pass

class LedgerNotImplementedError(LedgerParsingError, NotImplementedError):
    """Raised when a specific vendor key has no cleaning implementation."""
    pass

class ReconciliationError(ZohoUsableError, ValueError):
    """Raised when reconciliation or matching calculations encounter configuration or process errors."""
    pass
