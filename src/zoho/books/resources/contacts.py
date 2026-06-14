from typing import Any, Dict, Optional
import os
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class Contacts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'contacts')

    def enable_portal(self, contact_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', contact_id, 'portal/enable', data=data)

    def email_statement(self, contact_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._action('POST', contact_id, 'statements/email', data=data, params=params)

    def get_statement(self, contact_id: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        """
        Retrieve a statement for a contact.
        Returns binary content (e.g. XLS or PDF) depending on the parameters (e.g. accept='xls').
        """
        return self._action('GET', contact_id, 'statements', params=params)

    def download_statement(self, contact_id: str, save_path: str, params: Optional[Dict[str, Any]] = None) -> str:
        """
        Download a contact statement and save it to the specified path.
        """
        if not params:
            params = {}
        if 'accept' not in params:
            params['accept'] = 'xls'

        if not os.path.isabs(save_path):
            save_path = os.path.join("output", save_path)
            save_path = os.path.abspath(save_path)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        content = self.get_statement(contact_id, params=params)
        with open(save_path, "wb") as f:
            f.write(content)
        return save_path

class Organizations(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'organizations')

class ChartOfAccounts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'chartofaccounts')

class Vendors(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'vendors')

    def get_statement(self, vendor_id: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        """
        Retrieve a statement for a vendor. 
        Returns binary content (e.g. XLS or PDF) depending on the parameters (e.g. accept='xls').
        """
        return self._action('GET', vendor_id, 'statements', params=params)

    def download_statement(self, vendor_id: str, save_path: str, params: Optional[Dict[str, Any]] = None) -> str:
        """
        Download a vendor statement and save it to the specified path.
        """
        if not params:
            params = {}
        if 'accept' not in params:
            params['accept'] = 'xls'

        if not os.path.isabs(save_path):
            save_path = os.path.join("output", save_path)
            save_path = os.path.abspath(save_path)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        content = self.get_statement(vendor_id, params=params)
        with open(save_path, "wb") as f:
            f.write(content)
        return save_path

