"""Read-only checks performed before preparing the monthly GSTR-1 return."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from zoho.books.resources.gst import parse_doc_number


_STATUS_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class GSTR1VerificationConfig:
    """Policy settings for GSTR-1 verification."""

    e_invoice_applicable: bool = True
    fiscal_year_start_month: int = 4

    def __post_init__(self) -> None:
        if not 1 <= self.fiscal_year_start_month <= 12:
            raise ValueError("fiscal_year_start_month must be between 1 and 12.")


def _month_range(month: str) -> Tuple[date, date]:
    try:
        parsed = datetime.strptime(month.strip(), "%Y-%m").date()
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid month {month!r}; expected YYYY-MM.") from exc
    last_day = calendar.monthrange(parsed.year, parsed.month)[1]
    return parsed.replace(day=1), parsed.replace(day=last_day)


def _previous_month_range(as_of: Optional[date] = None) -> Tuple[date, date]:
    current = as_of or date.today()
    first_of_month = current.replace(day=1)
    previous_end = first_of_month - timedelta(days=1)
    return previous_end.replace(day=1), previous_end


def _first(record: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _document_info(record: Mapping[str, Any], document_type: str) -> Dict[str, Any]:
    if document_type == "invoice":
        doc_id = _first(record, ("invoice_id", "id"))
        number = _first(record, ("invoice_number", "number"))
    else:
        doc_id = _first(record, ("creditnote_id", "credit_note_id", "id"))
        number = _first(record, ("creditnote_number", "credit_note_number", "number"))
    return {
        "document_type": document_type,
        "id": str(doc_id) if doc_id is not None else None,
        "number": str(number).strip() if number is not None else None,
        "date": str(record.get("date") or ""),
        "status": str(record.get("status") or ""),
        "customer_name": _first(record, ("customer_name", "contact_name")),
        "total": record.get("total"),
        "location_id": str(record.get("location_id") or "") or None,
        "location_name": record.get("location_name"),
    }


class GSTR1Verifier:
    """Build an evidence-based, non-mutating GSTR-1 readiness report."""

    def __init__(self, books_client: Any, config: Optional[GSTR1VerificationConfig] = None):
        self.books = books_client
        self.config = config or GSTR1VerificationConfig()

    def run(self, month: Optional[str] = None, as_of: Optional[date] = None) -> Dict[str, Any]:
        start, end = _month_range(month) if month is not None else _previous_month_range(as_of)
        fy_start, fy_end = self._financial_year_range(start)
        fetch_errors: List[Dict[str, str]] = []

        locations = self._safe_list_locations(fetch_errors)

        target_invoices = self._safe_list_documents(
            self.books.invoices, "invoices", start, end, fetch_errors
        )
        target_credit_notes = self._safe_list_documents(
            self.books.credit_notes, "credit_notes", start, end, fetch_errors
        )
        sequence_invoices = self._safe_list_documents(
            self.books.invoices, "invoices_sequence", fy_start, fy_end, fetch_errors
        )
        sequence_credit_notes = self._safe_list_documents(
            self.books.credit_notes, "credit_notes_sequence", fy_start, fy_end, fetch_errors
        )

        registration_meta, location_to_registration = self._registration_metadata(locations)
        grouped_target_invoices = self._group_by_registration(
            target_invoices, location_to_registration
        )
        grouped_target_credit_notes = self._group_by_registration(
            target_credit_notes, location_to_registration
        )
        grouped_sequence_invoices = self._group_by_registration(
            sequence_invoices, location_to_registration
        )
        grouped_sequence_credit_notes = self._group_by_registration(
            sequence_credit_notes, location_to_registration
        )
        registration_keys = sorted(
            set(grouped_target_invoices) | set(grouped_target_credit_notes)
        )

        registration_reports: Dict[str, Dict[str, Any]] = {}
        for registration_key in registration_keys:
            raw_invoices = grouped_target_invoices.get(registration_key, [])
            raw_credit_notes = grouped_target_credit_notes.get(registration_key, [])
            invoice_docs = [_document_info(item, "invoice") for item in raw_invoices]
            credit_note_docs = [
                _document_info(item, "credit_note") for item in raw_credit_notes
            ]
            documents = invoice_docs + credit_note_docs
            drafts = [
                doc for doc in documents
                if doc["status"].strip().casefold() == "draft"
            ]
            voids = [
                doc for doc in documents
                if doc["status"].strip().casefold() == "void"
            ]
            sequence_check = self._merge_sequence_results(
                self._sequence_check(
                    invoice_docs,
                    [
                        _document_info(item, "invoice")
                        for item in grouped_sequence_invoices.get(registration_key, [])
                    ],
                ),
                self._sequence_check(
                    credit_note_docs,
                    [
                        _document_info(item, "credit_note")
                        for item in grouped_sequence_credit_notes.get(registration_key, [])
                    ],
                ),
            )
            einvoice_check = self._einvoice_check(raw_invoices, raw_credit_notes)
            draft_check = {
                "passed": not drafts,
                "count": len(drafts),
                "documents": drafts,
            }
            metadata = registration_meta.get(
                registration_key,
                self._fallback_registration_metadata(registration_key, documents),
            )
            registration_reports[registration_key] = {
                **metadata,
                "passed": (
                    draft_check["passed"]
                    and sequence_check["passed"]
                    and einvoice_check["passed"]
                ),
                "invoices": {"count": len(invoice_docs), "documents": invoice_docs},
                "credit_notes": {
                    "count": len(credit_note_docs),
                    "documents": credit_note_docs,
                },
                "checks": {
                    "draft_documents": draft_check,
                    "number_sequence": sequence_check,
                    "einvoice_push": einvoice_check,
                },
                "void_documents": voids,
            }

        invoice_docs = [
            doc
            for report in registration_reports.values()
            for doc in report["invoices"]["documents"]
        ]
        credit_note_docs = [
            doc
            for report in registration_reports.values()
            for doc in report["credit_notes"]["documents"]
        ]
        drafts = [
            doc
            for report in registration_reports.values()
            for doc in report["checks"]["draft_documents"]["documents"]
        ]
        voids = [
            doc
            for report in registration_reports.values()
            for doc in report["void_documents"]
        ]
        draft_check = {"passed": not drafts, "count": len(drafts), "documents": drafts}
        sequence_check = self._merge_sequence_results(
            *(report["checks"]["number_sequence"] for report in registration_reports.values())
        )
        einvoice_check = self._merge_einvoice_results(
            *(report["checks"]["einvoice_push"] for report in registration_reports.values())
        )
        complete = not fetch_errors
        overall_passed = (
            complete
            and draft_check["passed"]
            and sequence_check["passed"]
            and einvoice_check["passed"]
        )
        return {
            "period": {
                "month": start.strftime("%Y-%m"),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "sequence_scope_start": fy_start.isoformat(),
                "sequence_scope_end": fy_end.isoformat(),
            },
            "overall_passed": overall_passed,
            "complete": complete,
            "invoices": {"count": len(invoice_docs), "documents": invoice_docs},
            "credit_notes": {"count": len(credit_note_docs), "documents": credit_note_docs},
            "checks": {
                "draft_documents": draft_check,
                "number_sequence": sequence_check,
                "einvoice_push": einvoice_check,
            },
            "gst_registrations": registration_reports,
            "void_documents": voids,
            "warnings": [],
            "fetch_errors": fetch_errors,
        }

    def _financial_year_range(self, target_start: date) -> Tuple[date, date]:
        start_month = self.config.fiscal_year_start_month
        start_year = target_start.year if target_start.month >= start_month else target_start.year - 1
        start = date(start_year, start_month, 1)
        end_year = start_year + 1 if start_month > 1 else start_year
        end_month = start_month - 1 if start_month > 1 else 12
        end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
        return start, end

    @staticmethod
    def _safe_list_documents(
        resource: Any,
        source: str,
        start: date,
        end: date,
        errors: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        try:
            return resource.list_all(
                params={"date_start": start.isoformat(), "date_end": end.isoformat()}
            )
        except Exception as exc:
            errors.append({"source": source, "error": str(exc)})
            return []

    def _safe_list_locations(self, errors: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        try:
            return self.books.locations.list_all(resource_key="locations")
        except Exception as exc:
            errors.append({"source": "locations", "error": str(exc)})
            return []

    @staticmethod
    def _registration_metadata(
        locations: Sequence[Mapping[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        metadata: Dict[str, Dict[str, Any]] = {}
        location_to_registration: Dict[str, str] = {}
        for location in locations:
            location_id = str(location.get("location_id") or "")
            if not location_id:
                continue
            tax_settings_id = str(location.get("tax_settings_id") or "")
            registration_key = tax_settings_id or f"location:{location_id}"
            location_to_registration[location_id] = registration_key
            group = metadata.setdefault(
                registration_key,
                {
                    "gst_registration_key": registration_key,
                    "tax_settings_id": tax_settings_id or None,
                    "locations": [],
                },
            )
            group["locations"].append(
                {
                    "location_id": location_id,
                    "location_name": location.get("location_name"),
                }
            )
        for group in metadata.values():
            group["locations"].sort(key=lambda item: item["location_id"])
        return metadata, location_to_registration

    @staticmethod
    def _group_by_registration(
        documents: Sequence[Mapping[str, Any]],
        location_to_registration: Mapping[str, str],
    ) -> Dict[str, List[Mapping[str, Any]]]:
        grouped: Dict[str, List[Mapping[str, Any]]] = {}
        for document in documents:
            location_id = str(document.get("location_id") or "")
            registration_key = location_to_registration.get(location_id)
            if not registration_key:
                registration_key = f"location:{location_id}" if location_id else "unassigned"
            grouped.setdefault(registration_key, []).append(document)
        return grouped

    @staticmethod
    def _fallback_registration_metadata(
        registration_key: str,
        documents: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        locations = {}
        for document in documents:
            location_id = document.get("location_id")
            if location_id:
                locations[str(location_id)] = document.get("location_name")
        return {
            "gst_registration_key": registration_key,
            "tax_settings_id": None,
            "locations": [
                {"location_id": location_id, "location_name": name}
                for location_id, name in sorted(locations.items())
            ],
        }

    @staticmethod
    def _sequence_check(
        target_docs: Sequence[Mapping[str, Any]],
        universe_docs: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        active_target_docs = [
            doc
            for doc in target_docs
            if str(doc.get("status") or "").strip().casefold() != "void"
        ]
        target_ids = {
            doc.get("id") for doc in active_target_docs if doc.get("id") is not None
        }
        target_numbers = {
            doc.get("number")
            for doc in active_target_docs
            if doc.get("number") is not None
        }
        unparseable = []
        invalid_dates = []
        groups: Dict[str, List[Dict[str, Any]]] = {}
        occupied_sequences: Dict[str, Set[int]] = {}

        for doc in universe_docs:
            prefix, sequence, width = parse_doc_number(doc.get("number"))
            in_target = doc.get("id") in target_ids or doc.get("number") in target_numbers
            if sequence <= 0:
                if in_target:
                    unparseable.append(dict(doc))
                continue
            occupied_sequences.setdefault(prefix, set()).add(sequence)
            if str(doc.get("status") or "").strip().casefold() == "void":
                continue
            parsed_date = _parse_date(doc.get("date"))
            if parsed_date is None:
                if in_target:
                    invalid_dates.append(dict(doc))
                continue
            groups.setdefault(prefix, []).append(
                {**dict(doc), "prefix": prefix, "sequence": sequence, "width": width,
                 "parsed_date": parsed_date, "in_target": in_target}
            )

        missing: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        out_of_chronology: List[Dict[str, Any]] = []
        inconsistent_width: List[Dict[str, Any]] = []
        for prefix, items in groups.items():
            target_items = [item for item in items if item["in_target"]]
            if not target_items:
                continue
            by_sequence: Dict[int, List[Dict[str, Any]]] = {}
            for item in items:
                by_sequence.setdefault(item["sequence"], []).append(item)
            lower = min(item["sequence"] for item in target_items)
            upper = max(item["sequence"] for item in target_items)
            width = max(item["width"] for item in target_items)
            occupied_values = occupied_sequences[prefix]
            missing_values = {
                value for value in range(lower, upper + 1) if value not in occupied_values
            }
            ordered_values = sorted(occupied_values)
            previous_values = [value for value in ordered_values if value < lower]
            next_values = [value for value in ordered_values if value > upper]
            if previous_values:
                missing_values.update(range(previous_values[-1] + 1, lower))
            if next_values:
                missing_values.update(range(upper + 1, next_values[0]))
            for value in sorted(missing_values):
                missing.append({
                    "document_type": target_items[0]["document_type"],
                    "prefix": prefix,
                    "number": f"{prefix}{value:0{width}d}",
                })
            for value, same_number in by_sequence.items():
                if len(same_number) > 1 and any(item["in_target"] for item in same_number):
                    duplicates.append({
                        "document_type": target_items[0]["document_type"],
                        "prefix": prefix,
                        "sequence": value,
                        "documents": [GSTR1Verifier._public_sequence_doc(item) for item in same_number],
                    })
            widths = sorted({item["width"] for item in target_items})
            if len(widths) > 1:
                inconsistent_width.append({
                    "document_type": target_items[0]["document_type"],
                    "prefix": prefix,
                    "widths": widths,
                })
            ordered = sorted(items, key=lambda item: (item["sequence"], item["parsed_date"], item.get("id") or ""))
            for previous, current in zip(ordered, ordered[1:]):
                if current["sequence"] > previous["sequence"] and current["parsed_date"] < previous["parsed_date"]:
                    if current["in_target"] or previous["in_target"]:
                        out_of_chronology.append({
                            "document_type": current["document_type"],
                            "number": current["number"],
                            "date": current["date"],
                            "preceded_by": previous["number"],
                            "preceding_date": previous["date"],
                        })

        passed = not any((missing, duplicates, out_of_chronology, unparseable, invalid_dates, inconsistent_width))
        return {
            "passed": passed,
            "missing": missing,
            "duplicates": duplicates,
            "out_of_chronology": out_of_chronology,
            "unparseable_numbers": unparseable,
            "invalid_dates": invalid_dates,
            "inconsistent_width": inconsistent_width,
        }

    @staticmethod
    def _public_sequence_doc(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {key: item.get(key) for key in ("document_type", "id", "number", "date", "status")}

    @staticmethod
    def _merge_sequence_results(*results: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "missing", "duplicates", "out_of_chronology", "unparseable_numbers",
            "invalid_dates", "inconsistent_width",
        )
        merged = {key: [item for result in results for item in result[key]] for key in keys}
        merged["passed"] = all(result["passed"] for result in results)
        return merged

    @staticmethod
    def _merge_einvoice_results(*results: Mapping[str, Any]) -> Dict[str, Any]:
        if not results:
            return {
                "applicable": True,
                "skipped": False,
                "passed": True,
                "applicable_count": 0,
                "pushed": [],
                "exceptions": [],
                "not_applicable_or_not_returned": [],
            }
        return {
            "applicable": any(result["applicable"] for result in results),
            "skipped": all(result["skipped"] for result in results),
            "passed": all(result["passed"] for result in results),
            "applicable_count": sum(result["applicable_count"] for result in results),
            "pushed": [item for result in results for item in result["pushed"]],
            "exceptions": [item for result in results for item in result["exceptions"]],
            "not_applicable_or_not_returned": [
                item
                for result in results
                for item in result["not_applicable_or_not_returned"]
            ],
        }

    def _einvoice_check(
        self,
        invoices: Sequence[Mapping[str, Any]],
        credit_notes: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if not self.config.e_invoice_applicable:
            return {
                "applicable": False,
                "skipped": True,
                "passed": True,
                "reason": "E-invoicing is disabled by workflow configuration.",
                "applicable_count": 0,
                "pushed": [],
                "exceptions": [],
                "not_applicable_or_not_returned": [],
            }

        pushed: List[Dict[str, Any]] = []
        exceptions: List[Dict[str, Any]] = []
        not_applicable: List[Dict[str, Any]] = []
        applicable_count = 0
        for document_type, docs in (
            ("invoice", invoices),
            ("credit_note", credit_notes),
        ):
            for raw_doc in docs:
                doc = _document_info(raw_doc, document_type)
                if doc["status"].strip().casefold() in {"draft", "void"}:
                    continue
                details = raw_doc.get("einvoice_details")
                if not isinstance(details, Mapping) or not details:
                    not_applicable.append(doc)
                    continue
                applicable_count += 1
                outcome = self._classify_einvoice(details)
                detail = {**doc, **outcome}
                if outcome["classification"] == "pushed" and outcome["registration_reference"]:
                    pushed.append(detail)
                else:
                    exceptions.append(detail)

        return {
            "applicable": True,
            "skipped": False,
            "passed": not exceptions,
            "applicable_count": applicable_count,
            "pushed": pushed,
            "exceptions": exceptions,
            "not_applicable_or_not_returned": not_applicable,
        }

    @staticmethod
    def _classify_einvoice(record: Mapping[str, Any]) -> Dict[str, Any]:
        raw_status = _first(
            record,
            ("einvoice_status", "e_invoice_status", "e-invoice_status", "status"),
        )
        token = _STATUS_TOKEN.sub("", str(raw_status or "").casefold())
        if token in {"pushed", "manuallypushed"}:
            classification = "pushed"
        elif token in {"yettobepushed", "readytopush", "notpushed"}:
            classification = "not_pushed"
        elif token == "pushinitiated":
            classification = "pending"
        elif token == "failed":
            classification = "failed"
        elif token in {"cancelled", "markedascancelled"}:
            classification = "cancelled"
        else:
            classification = "unknown"
        reference = _first(
            record,
            ("inv_ref_num", "irn", "uuid", "invoice_reference_number"),
        )
        return {
            "einvoice_status": raw_status,
            "classification": classification,
            "registration_reference": reference,
            "acknowledgement_number": _first(record, ("ack_no", "ack_number", "acknowledgement_number")),
        }


def verify_gstr1(
    books_client: Any,
    month: Optional[str] = None,
    as_of: Optional[date] = None,
    config: Optional[GSTR1VerificationConfig] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :class:`GSTR1Verifier`."""
    return GSTR1Verifier(books_client, config=config).run(month=month, as_of=as_of)
