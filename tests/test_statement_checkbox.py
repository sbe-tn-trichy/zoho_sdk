import pytest

from workflows.statement_schedules import checkbox_formula_updates

PERIODS = [{'start': '2024-04-01', 'end': '2025-03-31'},
           {'start': '2025-04-01', 'end': '2026-03-31'}]
SHEETS = {'notes': 'Notes to Accounts', 'balancesheet': 'Balance Sheet',
          'profitandloss': 'Profit and Loss'}


def test_configured_mapping_refreshes_only_matching_checkbox_lookup():
    mapping = {'year': '2024–25', 'section': 'Audited combined lines',
               'line_item': 'Sundry Creditors', 'note_lines': ['Accounts Payable', 'B+L  Scheme']}
    rows = [[], ['2024–25', 'Audited', 'Audited combined lines', 'Sundry Creditors',
                 3239051.98, '', '', '=old'],
            ['2025–26', 'AIS', 'Audited combined lines', 'Sundry Creditors', 1, '', '', '=keep']]
    updates = checkbox_formula_updates(rows, sheet='checkbox', periods=PERIODS,
                                      sheets=SHEETS, mappings=[mapping])
    formula = updates["'checkbox'!H2"][0][0]
    assert 'SUM(XLOOKUP(' in formula
    assert '$C$1:$C$500' in formula
    assert 'COUNTIF' in formula and '"B+L  Scheme"' in formula
    assert "'checkbox'!H3" not in updates
    assert all(address.split('!')[1][0] in 'GHIK' for address in updates)
    assert rows[1][4] == 3239051.98


@pytest.mark.parametrize('changes', [
    {'year': '2023–24'}, {'note_lines': []}, {'note_lines': ['A', 'A']},
    {'note_lines': ['A', 1]}, {'line_item': ''},
])
def test_invalid_configured_mapping_fails(changes):
    mapping = {'year': '2024–25', 'section': 'Audited combined lines',
               'line_item': 'Sundry Creditors', 'note_lines': ['Accounts Payable']}
    mapping.update(changes)
    with pytest.raises(ValueError, match='checkbox mapping'):
        checkbox_formula_updates([], sheet='checkbox', periods=PERIODS,
                                 sheets=SHEETS, mappings=[mapping])


def test_duplicate_configured_mapping_fails():
    mapping = {'year': '2024–25', 'section': 'Audited combined lines',
               'line_item': 'Sundry Creditors', 'note_lines': ['Accounts Payable']}
    with pytest.raises(ValueError, match='duplicate checkbox mapping'):
        checkbox_formula_updates([], sheet='checkbox', periods=PERIODS,
                                 sheets=SHEETS, mappings=[mapping, mapping])


def test_refresh_uses_current_row_and_year_preserving_inputs():
    rows = [[], ['2025–26', 'AIS', 'Profit and Loss', 'Revenue "quoted"', 53882147, 0,
                 '=old', '=old', '=old', 'Evidence', '=old'],
            ['2024–25', 'Audited', 'Note 10: Assets', 'TDS', 164299]]
    updates = checkbox_formula_updates(rows, sheet='checkbox', periods=PERIODS, sheets=SHEETS)
    assert '$C$1:$C$500' in updates["'checkbox'!H2"][0][0]
    assert 'Revenue ""quoted""' in updates["'checkbox'!H2"][0][0]
    assert '$C$1:$C$500' in updates["'checkbox'!H3"][0][0]
    assert 'E2=""' in updates["'checkbox'!G2"][0][0]
    assert 'ROUND(H2-G2,2)' in updates["'checkbox'!I2"][0][0]
    assert all(address.split('!')[1][0] in 'GHIK' for address in updates)
    assert rows[1][4:6] == [53882147, 0]


def test_custom_aggregate_lookup_is_preserved():
    rows = [['2024–25', 'Audited', 'Audited combined lines', 'Travel', 100, '', '', '=SUM(A1:A2)']]
    updates = checkbox_formula_updates(rows, sheet='checkbox', periods=PERIODS, sheets=SHEETS)
    assert "'checkbox'!H1" not in updates
    assert "'checkbox'!K1" in updates


def test_unknown_section_requires_existing_lookup():
    with pytest.raises(ValueError, match='no workbook lookup'):
        checkbox_formula_updates([['2024–25', '', 'Unknown', 'Item']],
                                 sheet='checkbox', periods=PERIODS, sheets=SHEETS)


def test_large_check_list_combines_reads_without_crossing_blank_rows():
    row = ['2025–26', 'AIS', 'Profit and Loss', 'Sales']
    updates = checkbox_formula_updates([row] * 40 + [[]] + [row] * 40,
                                      sheet='checkbox', periods=PERIODS, sheets=SHEETS)
    assert len(updates) == 8
    assert len(updates["'checkbox'!H1:H40"]) == 40
    assert 'E42=""' in updates["'checkbox'!G42:G81"][0][0]
