import logging
import requests
logger = logging.getLogger("zoho_cliq")

class ZohoCliqAPI:
    def __init__(self, access_token: str, bot_name: str = "messengerbot", domain: str = "in"):
        self.access_token = access_token
        self.bot_name = bot_name or "messengerbot"
        self.domain = domain or "in"
        self.base_url = f"https://cliq.zoho.{self.domain}/api/v2"


    def send_notification(self, message: str, channel: str = None):
        """Sends a summary message via direct Zoho Cliq API (v2)."""
        if not self.access_token:
            logger.warning("Cliq Access Token not provided. Skipping notification.")
            return
        
        if channel:
            # Send to specific channel
            url = f"{self.base_url}/channels/{channel}/message"
        else:
            # Send to bot (fallback)
            url = f"{self.base_url}/bots/{self.bot_name}/message"
            
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "text": message
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Cliq notification sent successfully via API to bot: {self.bot_name}")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send Cliq notification via API: {e}")
            return None
