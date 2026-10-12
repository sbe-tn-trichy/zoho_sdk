"""Refresh comparison formulas without replacing reviewed source inputs."""
from typing import Any, Mapping, Sequence

from .workflow import qualified


def checkbox_formula_updates(
    rows: Sequence[Sequence[Any]], *, sheet: str,
    periods: Sequence[Mapping[str, str]], sheets: Mapping[str, str],
    mappings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, list[list[Any]]]:
    """Build formulas for existing A:K checks, retaining custom combined lookups."""
    ordered = sorted(periods, key=lambda p: p['end'], reverse=True)
    years = {p['start'][:4] + '–' + p['end'][2:4]: i for i, p in enumerate(ordered)}
    configured = {}
    for mapping in mappings:
        identity = (mapping.get('year'), mapping.get('section'), mapping.get('line_item'))
        labels = mapping.get('note_lines')
        if (identity[0] not in years or not all(isinstance(x, str) and x for x in identity)
                or not isinstance(labels, list) or not labels
                or not all(isinstance(x, str) and x for x in labels)
                or len(set(labels)) != len(labels) or identity in configured):
            raise ValueError('Invalid or duplicate checkbox mapping')
        configured[identity] = labels
    result: dict[str, list[list[Any]]] = {}
    for number, source in enumerate(rows, 1):
        row = list(source) + [''] * (11 - len(source))
        if row[0] not in years or not row[3]:
            continue
        index = years[row[0]]
        if index > 1:
            raise ValueError('Checkbox supports two financial years')
        section = row[2]
        key = ('notes' if str(section).startswith('Note ') else
               next((k for k in ('balancesheet', 'profitandloss') if sheets[k] == section), None))
        labels = configured.get((row[0], section, row[3]))
        if labels:
            names = qualified(sheets['notes'], '$A$1:$A$500')
            amounts = qualified(sheets['notes'], f'${chr(ord("B") + index)}$1:${chr(ord("B") + index)}$500')
            escaped = [label.replace('"', '""') for label in labels]
            guards = ','.join(f'COUNTIF({names},"{label}")=1' for label in escaped)
            lookups = ','.join(f'XLOOKUP("{label}",{names},{amounts},"Missing / duplicate",0)' for label in escaped)
            result[qualified(sheet, f'H{number}')] = [[
                f'=IF(AND({guards}),SUM({lookups}),"Missing / duplicate")']]
        elif key:
            label = str(row[3]).replace('"', '""')
            column = chr(ord('B' if key == 'notes' else 'C') + index)
            names = qualified(sheets[key], '$A$1:$A$500')
            amounts = qualified(sheets[key], f'${column}$1:${column}$500')
            actual = (f'=IF(COUNTIF({names},"{label}")=1,'
                      f'XLOOKUP("{label}",{names},{amounts},"Missing / duplicate",0),"Missing / duplicate")')
            result[qualified(sheet, f'H{number}')] = [[actual]]
        elif not row[7]:
            raise ValueError(f'Checkbox row {number} has no workbook lookup for {section!r}')
        result[qualified(sheet, f'G{number}')] = [[
            f'=IF(E{number}="","",IF(AND(ISNUMBER(E{number}),OR(F{number}="",ISNUMBER(F{number}))),'
            f'E{number}+IF(F{number}="",0,F{number}),"Invalid input"))']]
        result[qualified(sheet, f'I{number}')] = [[
            f'=IF(AND(ISNUMBER(G{number}),ISNUMBER(H{number})),ROUND(H{number}-G{number},2),"")']]
        result[qualified(sheet, f'K{number}')] = [[
            f'=IF(E{number}="","Pending",IF(NOT(ISNUMBER(G{number})),"Review",'
            f'IF(NOT(ISNUMBER(H{number})),"Missing / duplicate",IF(I{number}=0,"Match","Review"))))']]
    # Keep Google read URLs bounded even when hundreds of checks are present.
    if len(result) > 100:
        combined: dict[str, list[list[Any]]] = {}
        for column in 'GHIK':
            cells = sorted((int(address.rsplit('!', 1)[1][1:]), values)
                           for address, values in result.items()
                           if address.rsplit('!', 1)[1].startswith(column))
            start = previous = 0
            block: list[list[Any]] = []
            for number, values in cells:
                if block and number != previous + 1:
                    combined[qualified(sheet, f'{column}{start}:{column}{previous}')] = block
                    block = []
                if not block:
                    start = number
                block.extend(values)
                previous = number
            if block:
                combined[qualified(sheet, f'{column}{start}:{column}{previous}')] = block
        return combined
    return result
