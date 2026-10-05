"""Polycab PDF interpretation, separate from Books orchestration."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from workflows.core.matching import parse_currency_amount, parse_date
from .models import CreditMemoEvidence


def parse_credit_memo_text(text: str) -> CreditMemoEvidence:
    """Parse Poppler layout text strictly; blank neighboring fields are not values."""
    if 'POLYCAB INDIA LIMITED' not in ' '.join(text.upper().split()):
        raise ValueError('PDF is not a Polycab supplier note')
    def value(label: str, pattern: str) -> str:
        match = re.search(label + r'[ \t]*:[ \t]*(' + pattern + ')', text, re.I)
        return match[1] if match else ''

    number = value(r'AR Invoice Number', r'\d+')
    date_text = re.sub(r'Customer[ \t]+Invoice Date', 'Customer Date', text, flags=re.I)
    date_match = re.search(r'Invoice Date[ \t]*:[ \t]*(\d{1,2}-[A-Za-z]{3}-\d{4})', date_text, re.I)
    raw_date = date_match[1] if date_match else ''
    parsed_date = parse_date(raw_date)
    if not number or parsed_date is None:
        raise ValueError('PDF must contain a supplier AR number and valid invoice date')
    totals = re.findall(r'\bTOTAL[ \t]+([\d,.]+)[ \t]*(?:\n|$)', text)
    if len(totals) > 1 and len(set(totals)) > 1:
        raise ValueError('PDF has conflicting TOTAL values')
    if totals:
        total = parse_currency_amount(totals[0])
    else:
        if 'Total Value' not in text or '(Rupees' not in text:
            raise ValueError('PDF amount table is missing')
        table = text.split('Total Value', 1)[1].split('(Rupees', 1)[0]
        values = re.findall(r'[ \t]+[\d,.]+[ \t]+[\d,.]+[ \t]+[\d,.]+[ \t]+[\d,.]+[ \t]+([\d,]+\.\d{2})[ \t]*(?:\n|$)', table)
        if not values:
            raise ValueError('PDF has no readable amount')
        total = sum((parse_currency_amount(x) for x in values), start=parse_currency_amount('0'))
    if not total.is_finite() or total <= 0:
        raise ValueError('PDF amount must be finite and positive')
    if 'Debit Note' in text[:2000]:
        total = -total
    rso = value(r'RSO\s+(?:Number|No\.?)', r'\d+')
    invoice = value(r'Customer Invoice No\.?', r'(?:SBE|SB|BD|TN)[A-Za-z0-9/-]+')
    return CreditMemoEvidence(number, value(r'Credit Note No', r'(?:TN/\S+|\d+)'),
                              parsed_date, total, rso, invoice,
                              bool(rso or 'return type' in text.casefold()))


def read_credit_memo_pdf(path: Path, *, document_id: str = '',
                         pdftotext: str = 'pdftotext') -> CreditMemoEvidence:
    """Read all pages with Poppler; missing Poppler/image-only PDFs fail closed."""
    executable = shutil.which(pdftotext)
    if not executable:
        raise RuntimeError('Poppler pdftotext is required for the credit review')
    with path.open('rb') as handle:
        if handle.read(4) != b'%PDF':
            raise ValueError('Attachment is not a PDF')
    result = subprocess.run([executable, '-layout', str(path.resolve()), '-'],
                            capture_output=True, text=True, timeout=60, check=True)
    return replace(parse_credit_memo_text(result.stdout), document_id=document_id,
                   source_path=str(path.resolve()))


def distinct_memos(memos: tuple[CreditMemoEvidence, ...]) -> tuple[CreditMemoEvidence, ...]:
    """Ignore identical source-note copies, reject contradictory copies of a number."""
    unique: dict[str, CreditMemoEvidence] = {}
    for memo in memos:
        previous = unique.get(memo.supplier_number)
        if previous:
            fields = ('printed_number', 'date', 'amount', 'rso_number', 'invoice_number', 'is_return')
            if any(getattr(previous, key) != getattr(memo, key) for key in fields):
                raise ValueError(f'Conflicting PDFs for supplier note {memo.supplier_number}')
        else:
            unique[memo.supplier_number] = memo
    return tuple(unique.values())
