"""Read fixed assets and their valuation histories through the Books API."""
from __future__ import annotations

from typing import Any

from zoho.base_resource import BaseResource


class FixedAssets(BaseResource):
    def __init__(self, client: Any):
        super().__init__(client, "fixedassets")

    def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result = super().list(params)
        if result.get("code") != 0 or not isinstance(result.get("fixedassets"), list):
            raise ValueError("Invalid fixed asset list response")
        if not result["fixedassets"] and result.get("page_context", {}).get("has_more_page"):
            raise ValueError("Empty fixed asset list page claims more pages")
        return result

    def history(self, fixed_asset_id: str) -> list[dict[str, Any]]:
        """Return every history page; reject incomplete or duplicated valuations."""
        if not fixed_asset_id or "/" in fixed_asset_id:
            raise ValueError("A fixed asset ID is required")
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while True:
            response = self.client.request("GET", f"fixedassets/{fixed_asset_id}/history",
                                           params={"page": page, "per_page": 200})
            if response.get("code") != 0 or not isinstance(response.get("asset_history"), list):
                raise ValueError("Invalid fixed asset history response")
            entries = response["asset_history"]
            for entry in entries:
                identity = str(entry.get("valuation_id") or "")
                if not identity or identity in seen:
                    raise ValueError("Missing or repeated fixed asset valuation ID")
                seen.add(identity)
                rows.append(entry)
            if not response.get("page_context", {}).get("has_more_page", False):
                return rows
            if not entries:
                raise ValueError("Empty fixed asset history page claims more pages")
            page += 1
