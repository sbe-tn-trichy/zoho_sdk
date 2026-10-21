---
type: workflow
---

# Creator payment image OCR

`apps/review_creator_payment_images.py` owns the read-only evidence workflow.
`workflows.creator_payment_ocr` accepts an injected Creator client and OCR
callable. The CLI constructs its client through `workflows.core.auth`.

Run a small sample:

```sh
.venv/bin/python apps/review_creator_payment_images.py --limit 1
```

Omit `--limit` to review all records. It limits processed records per report,
though the report is fully paginated before applying the limit. `--criteria`
applies Creator criteria to both reports. `--creator-app`, `--online-report`,
`--cheque-report`, and `--image-field` override production defaults. SDK callers
can configure amount, reference, and date fields independently per source.

Defaults are app `order-management-new`, reports `Online_Payments` and `Cheques`,
image `Payment_Image`, amount `Payment_Amount`, reference `Reference`. Online
payments use `Payment_Date`; cheques use `Cheque_Date`, not their clearing date.
All report fields are requested so attachment values remain available.

Install the optional Python dependencies with `.venv/bin/pip install -e '.[ocr]'`
and install the Tesseract executable separately. The workflow runs pytesseract
locally with a 60-second timeout per image after EXIF orientation and grayscale
conversion, polarity normalization for dark images, and 2× enlargement for images
narrower than 1200 pixels. Images must be readable by Pillow; PDFs and unreadable images are
reported as errors. Handwriting and cheque MICR are not reliably recognized.

Creator's authenticated download endpoint is used with the API-returned
`filepath`; image URLs are never fetched directly. Multiple attachment values
are processed separately. OAuth requires `ZohoCreator.report.READ`.

`output/creator_payment_ocr/review.md` is a problems-only Markdown table. Each affected image shows its record ID,
failed/missing/ambiguous fields, corresponding Creator and OCR values, and an
image link. Matching fields and raw OCR text are omitted. Images use generated filenames below `images/` so remote filenames
cannot escape the output folder. `--output-dir` accepts relative or absolute
paths. Use a distinct directory to retain earlier run evidence; reruns replace
the report and reuse numbered filenames. Each processed image and record is
checkpointed atomically. Report, download, and OCR errors remain explicit;
the CLI exits nonzero if any error occurred. Missing images are counted separately.

Extraction recognizes labeled INR amounts and standalone thousands-grouped amount lines, transaction/UTR/UPI/cheque references,
and numeric ISO, day/month/year, or day-abbreviated-month-year dates. Matching
requires one distinct extracted value per field and an exact comparison with
Creator; references retain leading zeros. Missing, conflicting, and ambiguous
values require review. Amount balances elsewhere in the image can introduce
ambiguity, which intentionally prevents a match. OCR text matching is evidence
consistency only; it does not prove settlement, authenticity, or customer identity.
Customer identity is not inferred from screenshots or handwritten payee names.
The workflow never changes Creator, Books, or reconciliation status. Store local
payment evidence with the same access controls as other accounting exports.

A leading `7` that could be a misread rupee glyph is flagged as
`possible_currency_symbol_error` when dropping it would agree with Creator.
This diagnostic never changes the extracted amount or authorizes a match.
