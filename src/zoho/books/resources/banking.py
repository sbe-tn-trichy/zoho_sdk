from typing import Any, Dict, List, Union
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class BankAccounts(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'bankaccounts')

class BankTransactions(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'banktransactions')
        
    def get_matches(self, transaction_id: str) -> Dict[str, Any]:
        return self._action('GET', f"uncategorized/{transaction_id}", 'match')

    def match(
        self,
        transaction_id: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        payload = (
            {"transactions_to_be_matched": data}
            if isinstance(data, list)
            else data
        )
        return self._action(
            'POST', f"uncategorized/{transaction_id}", 'match', data=payload
        )

    def categorize_as_expense(self, transaction_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', f"uncategorized/{transaction_id}", 'categorize/expenses', data=data)

    def categorize_as_customer_payment(
        self,
        transaction_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._action(
            'POST',
            f"uncategorized/{transaction_id}",
            'categorize/customerpayments',
            data=data,
        )

    def unmatch(self, transaction_id: str, account_id: str) -> Dict[str, Any]:
        if not account_id:
            raise ValueError("account_id is required.")
        return self._action(
            'POST',
            transaction_id,
            'unmatch',
            params={"account_id": account_id},
        )

class Journals(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'journals')
        
    def publish(self, journal_id: str) -> Dict[str, Any]:
        return self._action('POST', journal_id, 'status/publish')
