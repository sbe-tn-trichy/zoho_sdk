"""Find unallocated Creator customers and validate jurisdiction-scoped beats."""

from __future__ import annotations

from typing import Any, TypedDict

from zoho.helpers.custom_fields import get_custom_field_value

from .core.exceptions import ReconciliationError


class BeatOption(TypedDict):
    id: str
    name: str


class UnallocatedCustomer(TypedDict):
    creator_id: str
    books_id: str
    name: str
    jurisdiction: str
    beats: list[BeatOption]


def _text(value: Any) -> str:
    return str(value or "").strip()


class CreatorBeatAllocationService:
    def __init__(self, books: Any, creator: Any, app: str, customer_report: str) -> None:
        self.books = books
        self.creator = creator
        self.app = app
        self.customer_report = customer_report

    def _customers(self) -> list[dict[str, Any]]:
        rows = self.creator.get_all_records(self.app, self.customer_report)
        if not isinstance(rows, list):
            raise ReconciliationError("Invalid Creator customer response")
        return rows

    def _beats(self) -> dict[str, list[BeatOption]]:
        rows = self.creator.get_all_records(self.app, "All_Beats")
        if not isinstance(rows, list):
            raise ReconciliationError("Invalid Creator beat response")
        by_jurisdiction: dict[str, list[BeatOption]] = {}
        for row in rows:
            jurisdiction = _text((row.get("Jurisdiction") or {}).get("Jurisdiction_Name"))
            beat_id, name = _text(row.get("ID")), _text(row.get("Beat_Name"))
            if jurisdiction and beat_id and name:
                by_jurisdiction.setdefault(jurisdiction.casefold(), []).append(
                    {"id": beat_id, "name": name}
                )
        for options in by_jurisdiction.values():
            options.sort(key=lambda option: option["name"].casefold())
        return by_jurisdiction

    def list_unallocated(self) -> list[UnallocatedCustomer]:
        contacts = self.books.contacts.list_customers()
        if not isinstance(contacts, list):
            raise ReconciliationError("Invalid Books customer response")
        by_books_id = {
            _text(contact.get("contact_id")): contact
            for contact in contacts
            if contact.get("contact_type") == "customer" and contact.get("status") == "active"
        }
        beats = self._beats()
        result: list[UnallocatedCustomer] = []
        for row in self._customers():
            if _text(row.get("Beat.Beat_Name")):
                continue
            books_id = _text(row.get("Customer_Id"))
            contact = by_books_id.get(books_id)
            if contact is None:
                continue
            jurisdiction = _text(get_custom_field_value(contact, "cf_jurisdiction"))
            result.append({
                "creator_id": _text(row.get("ID")),
                "books_id": books_id,
                "name": _text(row.get("Name")),
                "jurisdiction": jurisdiction,
                "beats": beats.get(jurisdiction.casefold(), []),
            })
        result.sort(key=lambda row: (not bool(row["beats"]), row["jurisdiction"].casefold(), row["name"].casefold()))
        return result

    def allocate(self, creator_id: str, books_id: str, beat_id: str) -> dict[str, str]:
        """Recheck the live records before updating one Creator customer."""
        if not all(_text(x).isdigit() for x in (creator_id, books_id, beat_id)):
            raise ReconciliationError("Customer and beat IDs must be numeric")
        matching = [row for row in self._customers() if _text(row.get("ID")) == creator_id]
        if len(matching) != 1 or _text(matching[0].get("Customer_Id")) != books_id:
            raise ReconciliationError("Creator customer no longer matches the selected Books customer")
        if _text(matching[0].get("Beat.Beat_Name")):
            raise ReconciliationError("This customer already has a beat; refresh the page")
        response = self.books.contacts.get(books_id)
        contact = response.get("contact") if isinstance(response, dict) else None
        if not isinstance(contact, dict) or _text(contact.get("contact_id")) != books_id:
            raise ReconciliationError("Books customer could not be verified")
        if contact.get("contact_type") != "customer" or contact.get("status") != "active":
            raise ReconciliationError("Books customer is no longer active")
        jurisdiction = _text(get_custom_field_value(contact, "cf_jurisdiction"))
        options = self._beats().get(jurisdiction.casefold(), [])
        beat = next((option for option in options if option["id"] == beat_id), None)
        if beat is None:
            raise ReconciliationError("The selected beat is unavailable for this jurisdiction")
        result = self.creator.update_records(
            self.app, self.customer_report, payload={"data": {"Beat": beat_id}},
            record_id=creator_id,
        )
        if not isinstance(result, dict) or result.get("code") != 3000:
            raise ReconciliationError("Creator did not confirm the beat update")
        return {"creator_id": creator_id, "beat": beat["name"], "jurisdiction": jurisdiction}
