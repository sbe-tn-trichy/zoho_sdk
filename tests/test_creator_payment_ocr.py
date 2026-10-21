from unittest.mock import MagicMock

from workflows.creator_payment_ocr import (
    PaymentOCRSource, extract_payment_details, cross_check_payment,
    review_creator_payment_images,
)
from zoho.creator import ZohoCreatorAPI


ROW = {"ID": "123", "Payment_Image": "/download?filepath=%2Fimage.jpg",
       "Payment_Amount": "1,250.00", "Reference": "001234", "Payment_Date": "21-Oct-2026"}
TEXT = "Amount: INR 1,250.00\nUTR: 001234\nDate: 21/10/2026"


def test_extraction_and_exact_match():
    details = extract_payment_details(TEXT)
    assert cross_check_payment(ROW, PaymentOCRSource("Online_Payments"), details) == {
        "amount": "match", "reference": "match", "date": "match"}


def test_ambiguity_missing_and_mismatch():
    details = extract_payment_details(TEXT + "\nAmount: Rs 999\nUTR: 567890")
    checks = cross_check_payment(ROW, PaymentOCRSource("x"), details)
    assert checks["amount"] == checks["reference"] == "ambiguous"
    checks = cross_check_payment(ROW, PaymentOCRSource("x"), extract_payment_details("Amount: 12"))
    assert checks == {"amount": "mismatch", "reference": "not_extracted", "date": "not_extracted"}
    assert cross_check_payment({}, PaymentOCRSource("x"), details)["amount"] == "invalid_creator_value"


def test_download_uses_api_not_attachment_url(tmp_path):
    client = ZohoCreatorAPI("fake", "owner")
    client.request = MagicMock(return_value=b"image")
    target = tmp_path / "image"
    client.download_file("app", "report", "123", "Image", str(target), filepath="/a.jpg")
    assert target.read_bytes() == b"image"
    client.request.assert_called_once_with(
        "GET", "data/owner/app/report/report/123/Image/download",
        params={"filepath": "/a.jpg"}, stream=True)


def test_workflow_download_checkpoint_and_missing_image(tmp_path):
    creator = MagicMock()
    creator.get_all_records.return_value = [ROW, {**ROW, "ID": "124", "Payment_Image": ""}]
    result = review_creator_payment_images(creator, sources=(PaymentOCRSource("x"),),
                                          output_dir=tmp_path, ocr=lambda _: TEXT)
    assert result["summary"] == {"match": 1, "missing_image": 1}
    assert creator.download_file.call_args.kwargs["filepath"] == "/image.jpg"
    report = (tmp_path / "review.md").read_text()
    assert "| match |" not in report
    assert "Missing image" in report
    assert "001234" in report
    assert "OCR text:" not in report
    assert not (tmp_path / "review.json").exists()
    creator.update_records.assert_not_called()


def test_image_failure_does_not_hide_later_records(tmp_path):
    creator = MagicMock()
    creator.get_all_records.return_value = [ROW, ROW]
    creator.download_file.side_effect = [RuntimeError("download failed"), None]
    result = review_creator_payment_images(creator, sources=(PaymentOCRSource("x"),),
                                          output_dir=tmp_path, ocr=lambda _: TEXT)
    assert result["summary"] == {"error": 1, "match": 1}


def test_multiple_images_and_untrusted_filename(tmp_path):
    creator = MagicMock()
    creator.get_all_records.return_value = [{**ROW, "Payment_Image": ["../../bad", {"filepath": "/b"}]}]
    result = review_creator_payment_images(creator, sources=(PaymentOCRSource("x"),), output_dir=tmp_path,
                                          ocr=lambda _: TEXT)
    assert len(result["entries"][0]["images"]) == 2
    for call in creator.download_file.call_args_list:
        assert str(tmp_path / "images") in call.args[4]


def test_report_failure_is_saved(tmp_path):
    creator = MagicMock()
    creator.get_all_records.side_effect = RuntimeError("unavailable")
    result = review_creator_payment_images(creator, output_dir=tmp_path)
    assert result["summary"] == {"error": 2}


def test_public_exports():
    from workflows import PaymentOCRSource as PublicSource
    from workflows import review_creator_payment_images as public_review
    assert PublicSource is PaymentOCRSource
    assert public_review is review_creator_payment_images


def test_local_tesseract_reads_generated_image(tmp_path):
    import shutil
    import pytest
    pytest.importorskip("pytesseract")
    image_module = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont
    from workflows.creator_payment_ocr import tesseract_image
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract executable unavailable")
    image = image_module.new("RGB", (1600, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "Amount: INR 1250.00", fill="black", font=ImageFont.load_default(size=64))
    path = tmp_path / "generated.png"
    image.save(path)
    assert "1250.00" in tesseract_image(path)


def test_markdown_preserves_errors_and_escapes_content():
    from workflows.creator_payment_ocr import render_payment_ocr_markdown
    report = render_payment_ocr_markdown({"app": "a|b", "summary": {"error": 1},
        "entries": [{"report": "x", "status": "error", "error": "bad <script>\nnext"}]})
    assert "<script>" not in report
    assert "bad &lt;script&gt;<br>next" in report
    assert "| Unavailable |" in report


def test_rupee_glyph_misread_is_never_silently_corrected():
    source = PaymentOCRSource("Online_Payments")
    row = {**ROW, "Payment_Amount": "6332.00"}
    checks = cross_check_payment(row, source, extract_payment_details("76,332"))
    assert checks["amount"] == "possible_currency_symbol_error"
    assert cross_check_payment(row, source, extract_payment_details("6,332"))["amount"] == "match"
    assert cross_check_payment(row, source, extract_payment_details("86,332"))["amount"] == "mismatch"
    assert extract_payment_details("629456849720\n0055").amounts == ()


def test_problem_table_omits_matching_fields_and_raw_text():
    from workflows.creator_payment_ocr import render_payment_ocr_markdown
    report = render_payment_ocr_markdown({"entries": [{"report": "Online_Payments",
        "record_id": "123", "status": "needs_review", "creator": ROW,
        "images": [{"status": "needs_review", "text": "RAW OCR NOT FOR TABLE",
                    "checks": {"amount": "match", "reference": "mismatch", "date": "match"},
                    "extracted": {"references": ["999999"]}}]}]})
    assert "Reference: Mismatch" in report
    assert "Reference: 001234" in report
    assert "999999" in report
    assert "Amount:" not in report
    assert "RAW OCR" not in report
