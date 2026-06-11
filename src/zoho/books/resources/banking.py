from typing import Any, Dict
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class BankAccounts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'bankaccounts')

class BankTransactions(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'banktransactions')
        
    def match(self, transaction_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', f"uncategorized/{transaction_id}", 'match', data=data)

    def categorize_as_expense(self, transaction_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', f"uncategorized/{transaction_id}", 'categorize/expenses', data=data)

class Journals(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'journals')
        
    def publish(self, journal_id: str) -> Dict[str, Any]:
        return self._action('POST', journal_id, 'status/publish')
