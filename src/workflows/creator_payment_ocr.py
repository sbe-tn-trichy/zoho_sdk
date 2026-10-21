"""Read-only Creator payment evidence extraction and conservative cross-checking."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from zoho.creator import ZohoCreatorAPI
from workflows.core.checkpoint import atomic_text_writer
from workflows.core.matching import parse_date, to_finite_decimal


@dataclass(frozen=True)
class PaymentOCRSource:
    report: str
    image_field: str = "Payment_Image"
    amount_field: str = "Payment_Amount"
    reference_field: str = "Reference"
    date_field: str = "Payment_Date"


DEFAULT_SOURCES = (PaymentOCRSource("Online_Payments"),
                   PaymentOCRSource("Cheques", date_field="Cheque_Date"))


@dataclass(frozen=True)
class OCRDetails:
    amounts: tuple[str, ...]
    references: tuple[str, ...]
    dates: tuple[str, ...]


def extract_payment_details(text: str) -> OCRDetails:
    """Extract labeled values only; unrelated balances and account digits are not evidence."""
    amounts = re.findall(
        r"(?:\bamount(?:\s+(?:paid|transferred))?\s*[:\-]?\s*(?:INR|Rs\.?|₹)?|INR|Rs\.?|₹)\s*([0-9][0-9,]*(?:\.\d{1,2})?)(?![\d.])",
        text, re.I,
    )
    # Payment apps may show only a large amount after the currency glyph is lost.
    # Require an entire line with thousands grouping to exclude bare account/ID digits.
    amounts.extend(re.findall(
        r"^\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.\d{1,2})?)\s*$", text, re.M,
    ))
    references = re.findall(
        r"(?:UTR(?:\s+(?:number|no\.?))?|UPI\s+(?:ref(?:erence)?|transaction\s+ID)|transaction\s+ID|reference(?:\s+(?:number|no\.?))?|cheque\s+(?:number|no\.?))\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{3,})",
        text, re.I,
    )
    dates = re.findall(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4})\b", text)
    return OCRDetails(tuple(dict.fromkeys(amounts)), tuple(dict.fromkeys(references)),
                      tuple(dict.fromkeys(dates)))


def cross_check_payment(row: dict[str, Any], source: PaymentOCRSource,
                        details: OCRDetails) -> dict[str, str]:
    """Require one distinct extracted value for each check; ambiguity stays reviewable."""
    checks = {}
    for name, field, values, convert in (
        ("amount", source.amount_field, details.amounts,
         lambda v: to_finite_decimal(v, allow_commas=True)),
        ("reference", source.reference_field, details.references,
         lambda v: str(v or "").strip().casefold() or None),
        ("date", source.date_field, details.dates, parse_date),
    ):
        expected = convert(row.get(field))
        converted = {convert(value) for value in values}
        converted.discard(None)
        currency_confusion = (
            name == "amount" and expected is not None and expected not in converted
            and any(str(value).startswith("7") and
                    to_finite_decimal(str(value)[1:], allow_commas=True) == expected
                    for value in values)
        )
        checks[name] = ("invalid_creator_value" if expected is None else
                        "not_extracted" if not converted else
                        "ambiguous" if len(converted) > 1 else
                        "match" if expected in converted else
                        "possible_currency_symbol_error" if currency_confusion else "mismatch")
    return checks


def tesseract_image(path: Path) -> str:
    """Run local OCR with EXIF orientation, grayscale, and a bounded OCR runtime."""
    from PIL import Image, ImageOps
    import pytesseract

    from PIL import ImageStat

    with Image.open(path) as image:
        prepared = ImageOps.grayscale(ImageOps.exif_transpose(image))
        # Dark payment screenshots confuse the rupee glyph with a leading digit.
        # Normalize polarity and enlarge small text without consulting Creator values.
        if ImageStat.Stat(prepared).mean[0] < 127:
            prepared = ImageOps.invert(prepared)
        if prepared.width < 1200:
            prepared = prepared.resize((prepared.width * 2, prepared.height * 2),
                                       Image.Resampling.LANCZOS)
        return pytesseract.image_to_string(prepared, timeout=60)


def _filepaths(value: Any) -> list[str | None]:
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("filepath") or item.get("file_path")
            if not item:
                raise ValueError("Attachment object has no filepath.")
        if not isinstance(item, str):
            raise ValueError("Unsupported attachment field value.")
        query = parse_qs(urlsplit(item).query)
        if query.get("filepath"):
            result.append(query["filepath"][0])
        elif item.startswith(("http:", "https:")) or "<" in item:
            raise ValueError("Attachment URL has no filepath; use API field values.")
        else:
            result.append(item)
    return result



def _markdown_cell(value: Any) -> str:
    from html import escape
    text = escape(str(value if value is not None else ""))
    for character in ("\\", "`", "*", "_", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text.replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def render_payment_ocr_markdown(result: dict[str, Any]) -> str:
    """Show problems only, one compact table row per affected image or record."""
    from urllib.parse import quote

    labels = {"not_extracted": "Not readable", "ambiguous": "Multiple OCR values",
              "mismatch": "Mismatch", "invalid_creator_value": "Missing/invalid Creator value",
              "possible_currency_symbol_error": "Possible ₹ misread as 7"}
    lines = ["# Payment image problems", "",
             "| Report | Record ID | Problem | Creator | OCR | Image |",
             "| --- | --- | --- | --- | --- | --- |"]
    count = 0
    for entry in result["entries"]:
        base = [_markdown_cell(entry["report"]), _markdown_cell(entry.get("record_id") or "Unavailable")]
        creator = entry.get("creator", {})
        fields = entry.get("comparison_fields", {
            "amount": "Payment_Amount", "reference": "Reference",
            "date": "Cheque_Date" if "Cheque_Date" in creator else "Payment_Date",
        })

        def add_row(problems: list[str], expected: list[str], observed: list[str], link: str = "—") -> None:
            nonlocal count
            cells = base + ["<br>".join(_markdown_cell(v) for v in values) or "—"
                            for values in (problems, expected, observed)] + [link]
            lines.append("| " + " | ".join(cells) + " |")
            count += 1

        if entry.get("error") or entry["status"] == "missing_image":
            add_row([entry.get("error") or "Missing image"],
                    [f"{name.title()}: {creator.get(field) or 'Missing'}" for name, field in fields.items()] if creator else [], [])
        for image in entry.get("images", []):
            link = f"[View](<{quote(str(image['path']), safe='/ :').replace(' ', '%20')}>)" if image.get("path") else "—"
            if image.get("error"):
                add_row([image["error"]], [], [], link)
                continue
            problems, expected, observed = [], [], []
            for field, status in image.get("checks", {}).items():
                if status == "match":
                    continue
                problems.append(f"{field.title()}: {labels.get(status, status)}")
                expected.append(f"{field.title()}: {creator.get(fields[field]) or 'Missing'}")
                candidates = image.get("extracted", {}).get({"amount": "amounts", "reference": "references", "date": "dates"}[field], [])
                observed.append(f"{field.title()}: {', '.join(candidates) or 'Not extracted'}")
            if problems:
                add_row(problems, expected, observed, link)
            elif image.get("status") == "error":
                add_row(["Image processing incomplete"], [], [], link)
    if not count:
        lines.append("| — | — | No problems found | — | — | — |")
    return "\n".join(lines) + "\n"


def review_creator_payment_images(
    creator: ZohoCreatorAPI, *, app: str = "order-management-new",
    sources: tuple[PaymentOCRSource, ...] = DEFAULT_SOURCES,
    output_dir: Path = Path("output/creator_payment_ocr"),
    criteria: str | None = None, limit: int | None = None,
    ocr: Callable[[Path], str] = tesseract_image,
) -> dict[str, Any]:
    """Download evidence and checkpoint each image; never write to Creator or Books.

    Absolute output directories are supported. Remote names never become local paths.
    A limit applies per source report. All failures remain visible in results.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"app": app, "entries": [], "summary": {}}

    def checkpoint() -> None:
        summary: dict[str, int] = {}
        for entry in result["entries"]:
            summary[entry["status"]] = summary.get(entry["status"], 0) + 1
        result["summary"] = summary
        with atomic_text_writer(output_dir / "review.md") as report:
            report.write(render_payment_ocr_markdown(result))

    for source in sources:
        try:
            rows = creator.get_all_records(app, source.report, criteria=criteria, field_config="all")
        except Exception as exc:
            result["entries"].append({"report": source.report, "status": "error", "error": str(exc)})
            checkpoint()
            continue
        for row in rows[:limit]:
            entry = {"report": source.report, "record_id": str(row.get("ID") or ""),
                     "comparison_fields": {"amount": source.amount_field, "reference": source.reference_field, "date": source.date_field},
                     "creator": {field: row.get(field) for field in
                                 (source.amount_field, source.reference_field, source.date_field)},
                     "images": [], "status": "needs_review"}
            result["entries"].append(entry)
            try:
                if not entry["record_id"]:
                    raise ValueError("Creator record is missing ID.")
                paths = _filepaths(row.get(source.image_field))
                if not paths:
                    entry["status"] = "missing_image"
                for filepath in paths:
                    image = {"status": "error"}
                    entry["images"].append(image)
                    # Numbered paths prevent path traversal and collisions between sources.
                    path = output_dir / "images" / f'{len(result["entries"]):06d}_{len(entry["images"]):02d}.image'
                    try:
                        creator.download_file(app, source.report, entry["record_id"],
                                              source.image_field, str(path), filepath=filepath)
                        image["path"] = str(path)
                        text = ocr(path)
                        details = extract_payment_details(text)
                        checks = cross_check_payment(row, source, details)
                        image.update(text=text, extracted=asdict(details), checks=checks,
                                     status="match" if all(v == "match" for v in checks.values()) else "needs_review")
                    except Exception as exc:
                        image["error"] = str(exc)
                    checkpoint()
                if paths:
                    states = [image["status"] for image in entry["images"]]
                    entry["status"] = "error" if "error" in states else "match" if all(s == "match" for s in states) else "needs_review"
            except Exception as exc:
                entry.update(status="error", error=str(exc))
            checkpoint()
    checkpoint()
    return result
