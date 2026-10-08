"""Register a customer in Books and Creator using a shared Books identity."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from zoho.books import ZohoBooksAPI
from zoho.creator import ZohoCreatorAPI

__all__ = ["CustomerRegistrationResult", "CustomerRegistrationError", "register_customer"]


@dataclass(frozen=True)
class CustomerRegistrationResult:
    dry_run: bool
    books_contact_id: str | None
    creator_record_id: str | None
    books_payload: dict[str, Any]
    creator_payload: dict[str, Any]
    books_contact_number: str | None = None


class CustomerRegistrationError(RuntimeError):
    """Registration failed; a Books contact may already exist."""

    def __init__(self, message: str, *, books_contact_id: str | None = None):
        self.books_contact_id = books_contact_id
        super().__init__(message)


def register_customer(
    books_client: ZohoBooksAPI,
    creator_client: ZohoCreatorAPI,
    creator_data: dict[str, Any],
    *,
    books_data: dict[str, Any] | None = None,
    app_link_name: str = "order-management-new",
    form_link_name: str = "Customer_Registration",
    dry_run: bool = False,
    existing_books_contact_id: str | None = None,
) -> CustomerRegistrationResult:
    """Create Books first, then Creator. Reuse an explicit ID for recovery.

    Only Name (or legacy Customer_Name) is mapped automatically. Supply other Books fields
    explicitly. Creator form workflows are skipped to avoid duplicate creation.
    No automatic rollback or retry is performed across the two services.
    """
    creator = deepcopy(creator_data)
    books = deepcopy(books_data) if books_data is not None else {}
    name = creator.get("Name", creator.get("Customer_Name"))
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Creator Name (or Customer_Name) must be a non-empty string.")
    books.setdefault("contact_name", name.strip())
    if not isinstance(books["contact_name"], str) or not books["contact_name"].strip():
        raise ValueError("Books contact_name must be a non-empty string.")
    if books.get("contact_type", "customer") != "customer":
        raise ValueError("Books contact_type must be customer.")
    books["contact_type"] = "customer"
    if not app_link_name.strip() or not form_link_name.strip():
        raise ValueError("Creator app and form link names are required.")
    contact_id = None
    if existing_books_contact_id is not None:
        contact_id = str(existing_books_contact_id).strip()
        if not contact_id or not contact_id.isdigit():
            raise ValueError("Existing Books contact ID must contain digits.")
    supplied_id = creator.get("Customer_Id")
    if supplied_id not in (None, "") and str(supplied_id) != contact_id:
        raise ValueError("Customer_Id requires a matching existing_books_contact_id.")
    creator["Customer_Id"] = contact_id or "<Books contact_id returned on creation>"
    creator["Customer_no"] = "<Books contact_number returned on creation or lookup>"
    payload = {"data": [creator], "skip_workflow": ["all"]}
    if dry_run:
        return CustomerRegistrationResult(True, contact_id, None, books, payload)
    if contact_id:
        response = books_client.contacts.get(contact_id)
        contact = response.get("contact", {})
        if response.get("code") != 0 or str(contact.get("contact_id")) != contact_id or contact.get("contact_type") != "customer":
            raise CustomerRegistrationError("Existing Books customer could not be verified.", books_contact_id=contact_id)
    else:
        response = books_client.contacts.create(books)
        contact = response.get("contact", {})
        if response.get("code") != 0 or not contact.get("contact_id"):
            raise CustomerRegistrationError("Books creation did not return a successful contact ID; inspect Books before retrying.")
        contact_id = str(contact["contact_id"])
    creator["Customer_Id"] = contact_id
    try:
        number = contact.get("contact_number")
        if not isinstance(number, str) or not number.strip():
            detail = books_client.contacts.get(contact_id)
            contact = detail.get("contact", {})
            if detail.get("code") != 0 or str(contact.get("contact_id")) != contact_id:
                raise ValueError("Books customer detail could not be verified.")
            number = contact.get("contact_number")
        if not isinstance(number, str) or not number.strip():
            raise ValueError("Books customer contact_number is missing or blank.")
        creator["Customer_no"] = number.strip()
        response = creator_client.add_records(app_link_name, form_link_name, payload=payload)
        records = response.get("result", response.get("data"))
        if isinstance(records, dict):
            records = [records]
        if response.get("code") != 3000 or not isinstance(records, list) or len(records) != 1:
            raise ValueError("Unexpected Creator response.")
        record = records[0]
        data = record.get("data", record)
        if record.get("code", 3000) != 3000 or not data.get("ID"):
            raise ValueError("Creator record was not confirmed successful.")
        record_id = str(data["ID"])
    except Exception as exc:
        raise CustomerRegistrationError(
            f"Books customer {contact_id} exists, but Creator creation was not confirmed. "
            "Check Creator before retrying; reuse existing_books_contact_id to avoid another Books customer.",
            books_contact_id=contact_id,
        ) from exc
    return CustomerRegistrationResult(False, contact_id, record_id, books, payload, number.strip())

from .numbers import CustomerNumberChange, CustomerNumberSyncResult, sync_customer_numbers

__all__ += ["CustomerNumberChange", "CustomerNumberSyncResult", "sync_customer_numbers"]
