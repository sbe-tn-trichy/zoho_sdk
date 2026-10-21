#!/usr/bin/env python3
"""Download Creator payment images and cross-check local Tesseract OCR evidence."""
from __future__ import annotations
import argparse
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401

from workflows.core.auth import get_creator_client
from workflows.creator_payment_ocr import PaymentOCRSource, review_creator_payment_images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-app", default="order-management-new")
    parser.add_argument("--online-report", default="Online_Payments")
    parser.add_argument("--cheque-report", default="Cheques")
    parser.add_argument("--image-field", default="Payment_Image")
    parser.add_argument("--criteria", help="Creator criteria applied to both reports")
    parser.add_argument("--limit", type=int, help="Maximum records per report")
    parser.add_argument("--output-dir", type=Path, default=Path("output/creator_payment_ocr"))
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    import shutil
    import importlib.util
    if not shutil.which("tesseract") or any(importlib.util.find_spec(m) is None for m in ("PIL", "pytesseract")):
        parser.error("Install zoho-sdk[ocr] and the Tesseract executable before running OCR.")
    result = review_creator_payment_images(
        get_creator_client(), app=args.creator_app,
        sources=(PaymentOCRSource(args.online_report, args.image_field),
                 PaymentOCRSource(args.cheque_report, args.image_field, date_field="Cheque_Date")),
        output_dir=args.output_dir, criteria=args.criteria, limit=args.limit,
    )
    print("| Status | Records |\n| --- | ---: |")
    for status, count in result["summary"].items():
        print(f"| {status} | {count} |")
    print(f"Review: {(args.output_dir / 'review.md').resolve()}")
    return 1 if result["summary"].get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
