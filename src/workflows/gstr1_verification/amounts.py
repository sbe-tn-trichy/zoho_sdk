"""Books document GST amounts and decimal-safe summaries."""
from decimal import Decimal
from typing import Any, Mapping, Sequence, TypedDict


class GSTAmounts(TypedDict):
    total_taxable: float
    igst: float
    cgst: float
    sgst: float
    total: float


KEYS = ('total_taxable', 'igst', 'cgst', 'sgst', 'total')


def document_amounts(record: Mapping[str, Any]) -> GSTAmounts:
    """Read authoritative document amounts; reject absent or unsupported taxes."""
    def amount(value: Any) -> Decimal:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError('Non-finite document amount')
        return result

    values = dict.fromkeys(KEYS, Decimal(0))
    values['total_taxable'] = amount(record['total_taxable_amount'])
    values['total'] = amount(record['total'])
    for tax in record['taxes']:
        name = str(tax.get('tax_specific_type') or tax.get('tax_name') or '').lower()
        value = amount(tax['tax_amount'])
        kind = next((key for key in ('igst', 'cgst', 'sgst') if key in name), None)
        if kind is None:
            if value:
                raise ValueError(f'Unsupported tax component: {name}')
        else:
            values[kind] += value
    if abs(sum(values[key] for key in ('igst', 'cgst', 'sgst')) - amount(record['tax_total'])) > Decimal('0.01'):
        raise ValueError('GST components do not reconcile to tax_total')
    return {key: float(value) for key, value in values.items()}


def summarize_amounts(invoices: Sequence[Mapping[str, Any]], credit_notes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sum active invoices and credits separately, then subtract credits."""
    complete = True
    totals = {}
    for kind, records in (('invoices', invoices), ('credit_notes', credit_notes)):
        values = dict.fromkeys(KEYS, Decimal(0))
        for record in records:
            if str(record.get('status', '')).strip().lower() in ('void', 'draft'):
                continue
            amounts = record.get('gst_amounts')
            if amounts is None:
                complete = False
                continue
            for key in KEYS:
                values[key] += Decimal(str(amounts[key]))
        totals[kind] = values
    totals['net'] = {key: totals['invoices'][key] - totals['credit_notes'][key] for key in KEYS}
    return {'complete': complete, **{kind: {key: float(value) for key, value in values.items()} for kind, values in totals.items()}}
