import logging
from typing import Any, Dict, Optional
from zoho.base_client import BaseZohoClient

logger = logging.getLogger("zoho_cliq")

class ZohoCliqAPI(BaseZohoClient):
    """
    Client for Zoho Cliq API.
    """
    def __init__(self, access_token: str, bot_name: str = "messengerbot", domain: str = "in"):
        self.bot_name = bot_name or "messengerbot"
        base_url = f"https://cliq.zoho.{domain or 'in'}/api/v2"
        super().__init__(
            access_token=access_token,
            domain=domain or "in",
            base_url=base_url,
            service_name="cliq"
        )

    def send_notification(self, message: str, channel: str = None) -> Optional[Dict[str, Any]]:
        """Sends a summary message via direct Zoho Cliq API (v2)."""
        if not self.access_token:
            logger.warning("Cliq Access Token not provided. Skipping notification.")
            return None
        
        if channel:
            endpoint = f"channels/{channel}/message"
        else:
            endpoint = f"bots/{self.bot_name}/message"
            
        payload = {
            "text": message
        }
        
        try:
            return self.request("POST", endpoint, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Cliq notification via API: {e}")
            return None
