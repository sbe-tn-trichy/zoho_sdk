from typing import Any, Dict, List, Optional

from ..base import BaseResource


class Locations(BaseResource):
    """Organization locations and their India tax-registration settings."""

    def __init__(self, client: Any):
        super().__init__(client, "locations")


class CustomFields:
    """Zoho Books custom-field settings endpoints."""

    def __init__(self, client: Any):
        self.client = client

    def list_for_entity(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not entity:
            raise ValueError("entity is required.")
        query = {"entity": entity, "filter_custom_fields": True}
        if params:
            query.update(params)
        response = self.client.request("GET", "settings/fields", params=query)
        fields = response.get("fields", []) if isinstance(response, dict) else []
        return fields if isinstance(fields, list) else []

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        required = ("label", "data_type", "entity", "show_on_pdf")
        missing = [name for name in required if name not in data]
        if missing:
            raise ValueError(
                f"Missing required custom-field values: {', '.join(missing)}"
            )
        return self.client.request("POST", "settings/fields", json=dict(data))
