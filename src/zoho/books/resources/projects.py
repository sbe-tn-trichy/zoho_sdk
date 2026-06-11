from typing import Any, Dict, Optional
from ..base import BaseResource
from ..mixins import ActiveInactiveMixin

class Projects(BaseResource, ActiveInactiveMixin):
    def __init__(self, client: Any):
        super().__init__(client, 'projects')

    def clone(self, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._action('POST', project_id, 'clone', data=data)

class Tasks(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'tasks')

class TimeEntries(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, 'projects/timeentries')

    def start_timer(self, time_entry_id: str) -> Dict[str, Any]:
        return self._action('POST', time_entry_id, 'timer/start')
        
    def stop_timer(self) -> Dict[str, Any]:
        return self._action('POST', None, 'timer/stop')
