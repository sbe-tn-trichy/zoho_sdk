class ZohoError(Exception):
    """Base exception class for all Zoho SDK errors."""
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
