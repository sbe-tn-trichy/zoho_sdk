"""Thin orchestration for Polycab attachment and accounting review."""
from __future__ import annotations

from datetime import date
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

from zoho.helpers.files import download_books_document
from zoho.security import resolve_output_path
from .evidence import credit_list, linked_candidates, read_record
from .models import CreditAudit, CreditFinding, CreditMemoEvidence, RmaCreditPolicy
from .pdf import distinct_memos, read_credit_memo_pdf
from .rules import evaluate, flag_shared_links


def review_polycab_vendor_credits(
    books_client: Any, *, policy: RmaCreditPolicy, from_date: date, to_date: date,
    credit_numbers: Sequence[str] = (), output_dir: Path = Path('output/polycab_credit_review'),
    journal_id: str = '', payment_id: str = '',
    pdf_reader: Callable[[Path], CreditMemoEvidence] = read_credit_memo_pdf,
) -> list[CreditAudit]:
    """Download/read attachments, collect linked evidence and evaluate domain rules.

    Explicit absolute output paths are honored; relative paths stay in output/.
    Overrides require exactly one selected credit. This function never writes Books.
    """
    selected = credit_list(books_client, policy, from_date, to_date, credit_numbers)
    if (journal_id or payment_id) and len(selected) != 1:
        raise ValueError('Explicit journal/payment IDs require exactly one selected credit')
    root = Path(resolve_output_path(str(output_dir)))
    root.mkdir(parents=True, exist_ok=True)
    audits = []
    for row in selected:
        credit = read_record(books_client.vendor_credits, row['vendor_credit_id'], 'vendor_credit', 'vendor_credit_id')
        if credit.get('vendor_id') != policy.vendor_id or credit.get('date') != row.get('date') or credit.get('vendor_credit_number') != row.get('vendor_credit_number'):
            raise ValueError('Credit detail no longer matches selected scope')
        memos, findings = [], []
        for document in credit.get('documents', []) or []:
            try:
                path = root / credit['vendor_credit_id'] / (str(document['document_id']) + '.pdf')
                saved = download_books_document(books_client, 'vendorcredits', credit['vendor_credit_id'], str(document['document_id']), str(path))
                memo = pdf_reader(Path(saved))
                memos.append(replace(memo, document_id=str(document['document_id']), source_path=str(Path(saved).resolve())))
            except Exception as exc:
                findings.append(CreditFinding('pdf_error', f"Attachment {document.get('document_id')}: {exc}", True))
        try:
            evidence = distinct_memos(tuple(memos))
        except ValueError as exc:
            findings.append(CreditFinding('pdf_error', str(exc), True))
            evidence = ()
        audits.append(CreditAudit(credit, evidence, None, None, findings))
    returns = [x for x in audits if x.is_rma]
    if returns:
        journal_rows = books_client.journals.list_all(params={'date_start': from_date.isoformat(), 'date_end': to_date.isoformat()}, resource_key='journals')
        payment_rows = books_client.customer_payments.list_all(params={'customer_id': policy.customer_id}, resource_key='customerpayments')
        journal_rows = [x for x in journal_rows if from_date <= date.fromisoformat(x['journal_date']) <= to_date]
        payment_rows = [x for x in payment_rows if x.get('customer_id') == policy.customer_id]
        if journal_id and not any(x.get('journal_id') == journal_id for x in journal_rows):
            journal_rows.append(read_record(books_client.journals, journal_id, 'journal', 'journal_id'))
        if payment_id and not any(x.get('payment_id') == payment_id for x in payment_rows):
            payment_rows.append(read_record(books_client.customer_payments, payment_id, 'payment', 'payment_id'))
        details: dict[tuple[str, str], dict[str, Any]] = {}
        for audit in returns:
            for kind, rows, override in [('journal', journal_rows, journal_id), ('payment', payment_rows, payment_id)]:
                match, link = linked_candidates(audit.credit, audit.memos, rows, kind=kind, override_id=override)
                setattr(audit, kind + '_link', link)
                if match:
                    resource = books_client.journals if kind == 'journal' else books_client.customer_payments
                    identifier = match[kind + '_id']
                    cache_key = kind, identifier
                    if cache_key not in details:
                        details[cache_key] = read_record(resource, identifier, kind, kind + '_id')
                    setattr(audit, kind, details[cache_key])
    return flag_shared_links([evaluate(audit, policy) for audit in audits])
