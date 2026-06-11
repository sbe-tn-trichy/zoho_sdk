from typing import Any, Dict, Optional

class ActiveInactiveMixin:
    def mark_as_active(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'active')

    def mark_as_inactive(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'inactive')

class StatusMixin:
    def mark_as_void(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'status/void')

    def mark_as_open(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'status/open')

    def mark_as_sent(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'status/sent')

    def mark_as_draft(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'status/draft')

class ApprovalMixin:
    def submit_for_approval(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'submit')

    def approve(self: Any, resource_id: str) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'approve')

class EmailMixin:
    def email(self: Any, resource_id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'email', data=data, params=params)

class CreditsMixin:
    def apply_credits(self: Any, resource_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', resource_id, 'credits', data=data)
