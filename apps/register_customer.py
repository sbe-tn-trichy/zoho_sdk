#!/usr/bin/env python3
"""Inspect Creator fields or register a customer in Books and Creator."""
import argparse
from dataclasses import asdict
import json
from typing import Any

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows.core.auth import get_books_client, get_creator_client
from workflows.customer_registration import register_customer


def inspect_form(
    app_link_name: str = "order-management-new",
    form_link_name: str = "Customer_Registration",
) -> dict[str, Any]:
    return get_creator_client().get_fields(app_link_name, form_link_name)


def create_customer_record(
    data: dict[str, Any],
    app_link_name: str = "order-management-new",
    form_link_name: str = "Customer_Registration",
    *,
    books_data: dict[str, Any] | None = None,
    dry_run: bool = False,
    existing_books_contact_id: str | None = None,
) -> dict[str, Any]:
    return asdict(register_customer(
        get_books_client(), get_creator_client(), data,
        books_data=books_data, app_link_name=app_link_name,
        form_link_name=form_link_name, dry_run=dry_run,
        existing_books_contact_id=existing_books_contact_id,
    ))


def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("Expected a JSON object.")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "create"], nargs="?", default="inspect")
    parser.add_argument("data", nargs="?", type=json_object)
    parser.add_argument("--books-data", type=json_object)
    parser.add_argument("--app", default="order-management-new")
    parser.add_argument("--form", default="Customer_Registration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Create records in both services (default).")
    mode.add_argument("--dry-run", action="store_true", help="Preview only; do not create records.")
    parser.add_argument("--existing-books-contact-id", help="Reuse a verified Books customer during recovery.")
    args = parser.parse_args()
    if args.action == "inspect":
        result = inspect_form(args.app, args.form)
    else:
        if args.data is None:
            parser.error("create requires a Creator customer JSON object")
        result = create_customer_record(
            args.data, args.app, args.form, books_data=args.books_data,
            dry_run=args.dry_run, existing_books_contact_id=args.existing_books_contact_id,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
