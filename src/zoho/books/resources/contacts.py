from typing import Any, Dict, Optional
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class Contacts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'contacts')

    def enable_portal(self, contact_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', contact_id, 'portal/enable', data=data)

    def email_statement(self, contact_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._action('POST', contact_id, 'statements/email', data=data, params=params)

class Organizations(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'organizations')

class ChartOfAccounts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'chartofaccounts')
