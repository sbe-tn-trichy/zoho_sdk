from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from zoho.inventory.resources.items import Items
from workflows.stock_transfer import (
    build_plan, build_payloads, line_total, split_plan, transaction_dates,
    validate_stock,
)


def item():
    stock = dict(location_stock_on_hand=10, location_available_stock=10,
                 location_actual_available_stock=10, location_available_for_sale_stock=6,
                 location_actual_available_for_sale_stock=6)
    return dict(item_id='1', sku='FAN', name='Fan', status='active', item_type='inventory',
                purchase_account_id='p', purchase_rate=100, rate=120,
                account_id='sales', inventory_account_id='asset', hsn_or_sac='8414', unit='NOS',
                item_tax_preferences=[dict(tax_specification='intra', tax_id='tax', tax_percentage=18)],
                locations=[dict(stock, location_id='source'), dict(stock, location_id='destination', location_stock_on_hand=-8)])


def test_caps_stock_and_commitments_and_revalidates():
    data = item()
    lines = build_plan([data], 'source', 'destination', ['p'])
    assert lines[0].quantity == 6
    assert lines[0].rate == Decimal('103.000000')
    data['locations'][0]['location_available_for_sale_stock'] = 5
    with pytest.raises(ValueError, match='Stock changed'):
        validate_stock(lines, [data], 'source', 'destination')


@pytest.mark.parametrize('source,destination,expected', [(3, -8, 3), (10, -2, 2), (0, -2, 0), (-2, -2, 0), (10, 0, 0)])
def test_shortage_and_source_bounds(source, destination, expected):
    data = item()
    data['locations'][0]['location_stock_on_hand'] = source
    data['locations'][1]['location_stock_on_hand'] = destination
    lines = build_plan([data], 'source', 'destination', ['p'])
    assert sum(line.quantity for line in lines) == expected


@pytest.mark.parametrize('value', [None, '', 'NaN', 'Infinity', 'broken'])
def test_unknown_stock_fails_closed(value):
    data = item()
    data['locations'][0]['location_available_stock'] = value
    with pytest.raises(ValueError):
        build_plan([data], 'source', 'destination', ['p'])


def test_scope_duplicate_and_batch_guards():
    data = item()
    with pytest.raises(ValueError, match='scoped'):
        build_plan([data], 'source', 'destination', ['other'])
    with pytest.raises(ValueError, match='Duplicate'):
        build_plan([data, data], 'source', 'destination', ['p'])
    data['track_batch_number'] = True
    with pytest.raises(ValueError, match='allocations'):
        build_plan([data], 'source', 'destination', ['p'])


def test_payloads_and_contact_gstin_guard():
    lines = build_plan([item()], 'source', 'destination', ['p'])
    source = dict(location_id='source', location_name='Source', tax_reg_no='33SOURCE', tax_settings_id='s', address={'state_code': 'TN'})
    dest = dict(source, location_id='destination', location_name='Destination', tax_reg_no='33DEST', tax_settings_id='d')
    customer = dict(contact_id='c', contact_type='customer', status='active', gst_no='33DEST')
    vendor = dict(contact_id='v', contact_type='vendor', status='active', gst_no='33SOURCE')
    pair = build_payloads(lines, source, dest, customer, vendor, date(2026, 9, 7), 'REF')
    assert pair['invoice']['line_items'][0]['quantity'] == pair['bill']['line_items'][0]['quantity'] == 6
    assert pair['bill']['line_items'][0]['account_id'] == 'asset'
    assert pair['invoice']['send'] is False
    vendor['gst_no'] = '33DEST'
    with pytest.raises(ValueError, match='vendor GSTIN'):
        build_payloads(lines, source, dest, customer, vendor, date(2026, 9, 7), 'REF')


def test_bulk_details_batches_deduplicates_and_orders():
    client = MagicMock()
    client.request.side_effect = [dict(code=0, items=[{'item_id': '2'}, {'item_id': '1'}]), dict(code=0, items=[{'item_id': '3'}])]
    result = Items(client).get_details(['1', '2', '1', '3'], batch_size=2)
    assert [i['item_id'] for i in result] == ['1', '2', '3']
    assert client.request.call_args_list[0].args == ('GET', 'itemdetails')
    assert client.request.call_args_list[0].kwargs['params'] == {'item_ids': '1,2'}


def test_bulk_details_missing_fails_and_empty_skips():
    client = MagicMock()
    assert Items(client).get_details([]) == []
    client.request.assert_not_called()
    client.request.return_value = dict(code=0, items=[])
    with pytest.raises(ValueError, match='Incomplete'):
        Items(client).get_details(['1'])
    with pytest.raises(ValueError):
        Items(client).get_details([''])


def test_bin_allocations_cap_and_revalidate():
    data = item()
    data['locations'][0]['is_storage_location_enabled'] = True
    data['transfer_bins'] = [dict(storage_id='a', location_id='source', status=1, balance_quantity=2),
                             dict(storage_id='b', location_id='source', status=1, balance_quantity=1),
                             dict(storage_id='c', location_id='source', status=1, balance_quantity=-3)]
    lines = build_plan([data], 'source', 'destination', ['p'])
    assert lines[0].quantity == 3
    assert lines[0].storages == [{'storage_id': 'a', 'out_quantity': 2.0}, {'storage_id': 'b', 'out_quantity': 1.0}]
    validate_stock(lines, [data], 'source', 'destination')
    data['transfer_bins'][0]['balance_quantity'] = 1
    with pytest.raises(ValueError, match='Bin stock changed'):
        validate_stock(lines, [data], 'source', 'destination')


def test_bin_enabled_missing_details_fails_closed():
    data = item()
    data['locations'][0]['is_storage_location_enabled'] = True
    with pytest.raises(KeyError, match='transfer_bins'):
        build_plan([data], 'source', 'destination', ['p'])


def test_transaction_dates_are_inclusive_and_exclude_sundays():
    assert transaction_dates(date(2026, 9, 5), date(2026, 9, 7)) == [
        date(2026, 9, 5), date(2026, 9, 7)
    ]
    with pytest.raises(ValueError):
        transaction_dates(date(2026, 9, 6), date(2026, 9, 6))


def test_split_plan_caps_final_value_and_preserves_quantity_and_bins():
    data = item()
    data['locations'][0]['is_storage_location_enabled'] = True
    data['transfer_bins'] = [dict(storage_id='a', location_id='source', status=1, balance_quantity=6)]
    lines = build_plan([data], 'source', 'destination', ['p'])
    documents = split_plan(lines, Decimal('250'))
    assert sum((line.quantity for document in documents for line in document), Decimal('0')) == Decimal('6')
    assert all(sum(line_total(line) for line in document) <= Decimal('250') for document in documents)
    assert sum(Decimal(str(storage['out_quantity'])) for document in documents for line in document for storage in line.storages) == Decimal('6')


def test_split_plan_rejects_one_unit_over_threshold():
    with pytest.raises(ValueError, match='exceeds'):
        split_plan(build_plan([item()], 'source', 'destination', ['p']), Decimal('100'))
