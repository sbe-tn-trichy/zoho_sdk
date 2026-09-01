#!/usr/bin/env python3
"""Inspect Zoho Creator Customer_Registration form and create customer record."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from workflows.core.auth import get_creator_client
from workflows.core.config import Config


def inspect_form(
    app_link_name: str = "order-management-new",
    form_link_name: str = "Customer_Registration",
) -> Dict[str, Any]:
    client = get_creator_client()
    fields_resp = client.get_fields(app_link_name, form_link_name)
    return fields_resp


def create_customer_record(
    data: Dict[str, Any],
    app_link_name: str = "order-management-new",
    form_link_name: str = "Customer_Registration",
) -> Dict[str, Any]:
    client = get_creator_client()
    payload = {"data": [data]}
    resp = client.add_records(app_link_name, form_link_name, payload)
    return resp


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    if action == "inspect":
        fields = inspect_form()
        print(json.dumps(fields, indent=2))
    elif action == "create":
        if len(sys.argv) > 2:
            payload_data = json.loads(sys.argv[2])
            res = create_customer_record(payload_data)
            print(json.dumps(res, indent=2))
