"""Scoped Books reads and conservative reference linkage."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Sequence

from workflows.core.matching import parse_date, references_intersect
from zoho.helpers.references import parse_reference_lines
from .models import CreditMemoEvidence, RmaCreditPolicy


def credit_list(books: Any, policy: RmaCreditPolicy, start: date, end: date,
                numbers: Sequence[str]) -> list[dict[str, Any]]:
    if start > end:
        raise ValueError('Credit date range is reversed')
    records = books.vendor_credits.list_all(
        params={'vendor_id': policy.vendor_id, 'date_start': start.isoformat(), 'date_end': end.isoformat()},
        resource_key='vendor_credits',
    )
    selected = []
    seen: set[str] = set()
    for row in records:
        day = parse_date(row.get('date'))
        if day is None:
            raise ValueError('Credit list has an invalid date')
        if str(row.get('vendor_id')) != policy.vendor_id or not start <= day <= end:
            continue  # Native filters can be ignored; enforce scope locally.
        if numbers and row.get('vendor_credit_number') not in numbers:
            continue
        identifier = str(row.get('vendor_credit_id') or '')
        if not identifier or identifier in seen:
            raise ValueError('Credit listing has missing or repeated IDs')
        seen.add(identifier)
        selected.append(row)
    missing = set(numbers) - {x['vendor_credit_number'] for x in selected}
    if missing:
        raise ValueError('Selected credits not found in scope: ' + ', '.join(sorted(missing)))
    if len({x['vendor_credit_number'] for x in selected}) != len(selected):
        raise ValueError('Ambiguous vendor credit numbers')
    return selected


def linked_candidates(credit: dict[str, Any], memos: tuple[CreditMemoEvidence, ...],
                      rows: Sequence[dict[str, Any]], *, kind: str,
                      override_id: str = '') -> tuple[dict[str, Any] | None, str]:
    """Exact references first; amount/date candidates remain explicitly inferred."""
    id_key = 'journal_id' if kind == 'journal' else 'payment_id'
    number_key = 'entry_number' if kind == 'journal' else 'payment_number'
    date_key = 'journal_date' if kind == 'journal' else 'date'
    if override_id:
        matches = [x for x in rows if x.get(id_key) == override_id]
        return (matches[0], 'explicit ID') if len(matches) == 1 else (None, 'ambiguous or missing explicit ID')
    references = [credit['vendor_credit_number']] + [m.supplier_number for m in memos]
    rso = [m.rso_number for m in memos if m.rso_number]
    credit_text = '\n'.join([credit.get('notes', '')] + [x.get('description', '') for x in credit.get('line_items', [])])
    labels = parse_reference_lines(credit_text)
    named = labels.get('JNL#' if kind == 'journal' else 'CP#', [])
    if kind == 'payment':
        named += [credit.get('reference_number', '')]
    matches = []
    for row in rows:
        text = row.get('reference_number', '') + '\n' + row.get('notes' if kind == 'journal' else 'description', '')
        tokens = re.findall(r'[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*', text)
        if (references_intersect(tokens, references + rso)
                or references_intersect([row.get(number_key)], named)):
            matches.append(row)
    if matches:
        return (matches[0], 'reference') if len(matches) == 1 else (None, 'ambiguous reference')
    # These candidates are for review only; never approve financial writes from amount alone.
    from .rules import money
    candidates = [x for x in rows if x.get(date_key) == credit.get('date')
                  and money(x.get('total' if kind == 'journal' else 'amount')) == money(credit['total'])]
    return (candidates[0], 'inferred amount/date') if len(candidates) == 1 else (None, 'missing or ambiguous')
