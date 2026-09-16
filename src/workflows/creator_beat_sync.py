"""Copy assigned Creator customer beats to the matching Books contact field."""

from __future__ import annotations

from typing import Any, TypedDict

from zoho.helpers.custom_fields import get_custom_field_value

from .core.exceptions import ReconciliationError


class BeatChange(TypedDict):
    books_id: str
    creator_id: str
    customer: str
    current: str
    beat: str


class BeatSyncResult(TypedDict):
    scanned: int
    skipped_unassigned: int
    skipped_inactive: int
    unchanged: int
    changes: list[BeatChange]
    updated: int


def _text(value: Any) -> str:
    return str(value or "").strip()


def sync_creator_beats(
    books: Any,
    creator: Any,
    app_link_name: str,
    customer_report: str,
    *,
    books_field: str = "cf_beat",
    apply: bool = False,
) -> BeatSyncResult:
    """Plan or apply Creator Beat.Beat_Name values for active Books customers.

    Blank Creator beats are ignored; this workflow never clears a Books beat.
    All candidates are validated before the first write.
    """
    fields = books.custom_fields.list_for_entity("contact")
    matching_fields = [field for field in fields if field.get("api_name") == books_field]
    if len(matching_fields) != 1 or not isinstance(matching_fields[0].get("index"), int):
        raise ReconciliationError(f"Books contact custom field {books_field!r} is missing or has no index")
    field_index = matching_fields[0]["index"]

    rows = creator.get_all_records(app_link_name, customer_report)
    if not isinstance(rows, list):
        raise ReconciliationError("Invalid Creator customer response")
    contacts = books.contacts.list_customers()
    if not isinstance(contacts, list):
        raise ReconciliationError("Invalid Books customer response")
    by_id = {_text(contact.get("contact_id")): contact for contact in contacts}
    if len(by_id) != len(contacts) or not all(by_id):
        raise ReconciliationError("Books customer list has duplicate or missing IDs")
    changes: list[BeatChange] = []
    seen: set[str] = set()
    skipped_unassigned = skipped_inactive = unchanged = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ReconciliationError("Invalid Creator customer record")
        beat = _text(row.get("Beat.Beat_Name"))
        if not beat:
            skipped_unassigned += 1
            continue
        books_id, creator_id = _text(row.get("Customer_Id")), _text(row.get("ID"))
        if not books_id.isdigit() or not creator_id.isdigit():
            raise ReconciliationError("Assigned Creator customer has an invalid Customer_Id or ID")
        if books_id in seen:
            raise ReconciliationError(f"Duplicate Creator records for Books customer {books_id}")
        seen.add(books_id)
        contact = by_id.get(books_id)
        if contact is None:
            skipped_inactive += 1
            continue
        if contact.get("contact_type") != "customer" or contact.get("status") != "active":
            raise ReconciliationError(f"Books contact {books_id} is not an active customer")
        current = _text(get_custom_field_value(contact, books_field))
        if current == beat:
            unchanged += 1
            continue
        changes.append({
            "books_id": books_id,
            "creator_id": creator_id,
            "customer": _text(contact.get("contact_name")),
            "current": current,
            "beat": beat,
        })

    updated = 0
    if apply:
        for change in changes:
            response = books.contacts.update(change["books_id"], {
                "custom_fields": [{"index": field_index, "value": change["beat"]}]
            })
            if not isinstance(response, dict) or response.get("code") != 0:
                raise ReconciliationError(f"Books did not confirm beat update for {change['books_id']}")
            updated += 1
    return {
        "scanned": len(rows), "skipped_unassigned": skipped_unassigned,
        "skipped_inactive": skipped_inactive, "unchanged": unchanged,
        "changes": changes, "updated": updated,
    }
