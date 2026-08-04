from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ..core.exceptions import SchemaValidationError


@dataclass(frozen=True)
class CreatorFieldRequirement:
    api_name: str
    allowed_types: Tuple[int, ...]
    required_choices: Tuple[str, ...] = ()
    expected_default: str = ""
    must_be_lookup: bool = False


COLLECTION_FIELD_REQUIREMENTS: Tuple[CreatorFieldRequirement, ...] = (
    CreatorFieldRequirement("Record_ID", (9,)),
    CreatorFieldRequirement("Payment_ID", (1, 9)),
    CreatorFieldRequirement("Payment_Date", (10,)),
    CreatorFieldRequirement("Amount", (6, 8)),
    CreatorFieldRequirement("Payment_Mode", (12,), ("Cash", "Online", "Cheque")),
    CreatorFieldRequirement("Reference_Number", (1,)),
    CreatorFieldRequirement("Customer_Name", (12,), must_be_lookup=True),
    CreatorFieldRequirement(
        "Reconciliation_Status",
        (12,),
        ("Pending", "Confirmed", "Unmatched_Manual"),
        "Pending",
    ),
    CreatorFieldRequirement("Zoho_Books_Payment_ID", (1,)),
)

AUDIT_FIELD_REQUIREMENTS: Tuple[CreatorFieldRequirement, ...] = (
    CreatorFieldRequirement("Creator_Record_ID", (1, 5, 9)),
    CreatorFieldRequirement("Stage", (1, 12)),
    CreatorFieldRequirement("Message", (1, 2)),
    CreatorFieldRequirement("Payload", (1, 2)),
    CreatorFieldRequirement("Occurred_At", (11,)),
)

BOOKS_CUSTOM_FIELD_REQUIREMENTS: Tuple[Dict[str, Any], ...] = (
    {
        "label": "Creator Record ID",
        "data_type": "string",
        "entity": "customer_payment",
        "show_on_pdf": False,
        "is_mandatory": False,
        "is_unique": True,
    },
    {
        "label": "Creator Payment ID",
        "data_type": "number",
        "entity": "customer_payment",
        "show_on_pdf": False,
        "is_mandatory": False,
        "is_unique": True,
    },
)


def _normalized_field_name(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _field_rows(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in ("fields", "data", "result"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, dict):
            nested = rows.get("fields") or rows.get("data")
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
    return []


def _creator_field_name(field: Mapping[str, Any]) -> str:
    return str(
        field.get("link_name")
        or field.get("api_name")
        or field.get("field_name")
        or field.get("name")
        or ""
    )


def _creator_field_type(field: Mapping[str, Any]) -> Any:
    value = field.get("type")
    if isinstance(value, dict):
        value = value.get("id") or value.get("value")
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _creator_choices(field: Mapping[str, Any]) -> List[str]:
    rows = field.get("choices") or field.get("values") or field.get("allowed_values") or []
    choices: List[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                value = row.get("value") or row.get("key") or row.get("name")
            else:
                value = row
            if value not in (None, ""):
                choices.append(str(value))
    return choices


def validate_creator_form_fields(
    payload: Any,
    requirements: Sequence[CreatorFieldRequirement],
) -> Dict[str, Any]:
    fields = {_creator_field_name(row): row for row in _field_rows(payload)}
    missing: List[str] = []
    wrong_types: List[Dict[str, Any]] = []
    wrong_choices: List[Dict[str, Any]] = []
    wrong_defaults: List[Dict[str, Any]] = []
    wrong_lookup_fields: List[str] = []
    unverified_defaults: List[str] = []
    for requirement in requirements:
        field = fields.get(requirement.api_name)
        if field is None:
            missing.append(requirement.api_name)
            continue
        actual_type = _creator_field_type(field)
        if actual_type not in requirement.allowed_types:
            wrong_types.append(
                {
                    "field": requirement.api_name,
                    "actual_type": actual_type,
                    "allowed_types": list(requirement.allowed_types),
                }
            )
        if requirement.required_choices:
            actual_choices = _creator_choices(field)
            absent = [
                choice for choice in requirement.required_choices
                if choice not in actual_choices
            ]
            if absent:
                wrong_choices.append(
                    {
                        "field": requirement.api_name,
                        "missing_choices": absent,
                        "actual_choices": actual_choices,
                    }
                )
        if requirement.expected_default:
            default_keys = ("default_value", "initial_value", "default")
            present_key = next((key for key in default_keys if key in field), None)
            if present_key is None:
                unverified_defaults.append(requirement.api_name)
            elif str(field.get(present_key) or "") != requirement.expected_default:
                wrong_defaults.append(
                    {
                        "field": requirement.api_name,
                        "expected": requirement.expected_default,
                        "actual": field.get(present_key),
                    }
                )
        if requirement.must_be_lookup and field.get("is_lookup_field") is not True:
            wrong_lookup_fields.append(requirement.api_name)
    return {
        "valid": (
            not missing
            and not wrong_types
            and not wrong_choices
            and not wrong_defaults
            and not wrong_lookup_fields
        ),
        "missing": missing,
        "wrong_types": wrong_types,
        "wrong_choices": wrong_choices,
        "wrong_defaults": wrong_defaults,
        "wrong_lookup_fields": wrong_lookup_fields,
        "unverified_defaults": unverified_defaults,
    }


def ensure_books_customer_payment_fields(
    books_client: Any,
    create_missing: bool = False,
) -> Dict[str, Any]:
    existing = books_client.custom_fields.list_for_entity("customer_payment")
    existing_by_name: Dict[str, Dict[str, Any]] = {}
    for field in existing:
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or "")
        api_name = str(field.get("api_name") or "")
        if api_name.startswith("cf_"):
            api_name = api_name[3:]
        for name in (label, api_name):
            normalized = _normalized_field_name(name)
            if normalized:
                existing_by_name[normalized] = field

    missing: List[Dict[str, Any]] = []
    misconfigured: List[Dict[str, Any]] = []
    for requirement in BOOKS_CUSTOM_FIELD_REQUIREMENTS:
        normalized = _normalized_field_name(requirement["label"])
        field = existing_by_name.get(normalized)
        if field is None:
            missing.append(dict(requirement))
            continue
        problems: List[str] = []
        if str(field.get("data_type") or "") != requirement["data_type"]:
            problems.append(
                f"data_type must be {requirement['data_type']!r}"
            )
        if requirement.get("is_unique") and field.get("is_unique") is not True:
            problems.append("field must be unique")
        required_values = {
            str(row["name"])
            for row in requirement.get("values", [])
            if isinstance(row, dict) and row.get("name")
        }
        actual_values = {
            str(row.get("name") or row.get("value") or "")
            for row in field.get("values", [])
            if isinstance(row, dict)
        }
        absent_values = sorted(required_values - actual_values)
        if absent_values:
            problems.append("missing dropdown values: " + ", ".join(absent_values))
        if problems:
            misconfigured.append(
                {"field": requirement["label"], "problems": problems}
            )

    created: List[Dict[str, Any]] = []
    if create_missing:
        for requirement in missing:
            created.append(books_client.custom_fields.create(requirement))
        missing = []
    return {
        "valid": not missing and not misconfigured,
        "missing": missing,
        "misconfigured": misconfigured,
        "created": created,
    }


def require_valid_schema(report: Mapping[str, Any]) -> None:
    invalid = [name for name, result in report.items() if not result.get("valid", False)]
    if invalid:
        raise SchemaValidationError(
            "Reconciliation schema validation failed for: " + ", ".join(invalid)
        )
