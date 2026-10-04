import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from zoho.books.resources.reports import Reports

ARGS = dict(account_ids=['a'], from_date='2022-08-01', to_date='2026-10-31')
RULE = {'columns': [{'index': 1, 'field': 'account_id', 'value': ['a'],
                     'comparator': 'in', 'group': 'report'}], 'criteria_string': '1'}


def response(option=0):
    result = {'code': 0, 'page_context': {
        'page': 1, 'from_date': ARGS['from_date'], 'to_date': ARGS['to_date'],
        'cash_based': 'false', 'filter_by': 'TransactionDate.CustomDate', 'rule': deepcopy(RULE)}}
    if option == 0:
        result['account_transactions'] = [{'account_transactions': [], 'opening_balance': {'credit': '0.00'}}]
        result['page_context']['has_more_page'] = False
    else:
        result['page_context'].update(total=66, total_pages=1)
    return result


@pytest.mark.parametrize('option', [0, 2])
def test_both_requests_preserve_payload_and_browser_parameters(option):
    client = Mock()
    client.request.return_value = response(option)
    result = Reports(client).account_transactions(**ARGS, response_option=option)
    assert result is client.request.return_value
    call = client.request.call_args
    assert call.args == ('GET', 'reports/accounttransaction')
    params = call.kwargs['params']
    assert params['response_option'] == option
    assert params['page'] == 1 and params['per_page'] == 500
    assert params['from_date'] == ARGS['from_date'] and params['to_date'] == ARGS['to_date']
    assert params['cash_based'] == 'false'
    assert params['filter_by'] == 'TransactionDate.CustomDate'
    assert params['show_sub_account'] == params['usestate'] == params['is_new_flow'] == 'false'
    assert json.loads(params['rule']) == RULE
    assert json.loads(params['group_by']) == [{'field': 'none', 'group': 'report'}]
    columns = json.loads(params['select_columns'])
    assert {'field': 'running_balance', 'group': 'report'} in columns
    assert columns[-1] == {'field': 'location_name', 'group': 'branch'}


@pytest.mark.parametrize('override', [
    {'account_ids': 'a'}, {'account_ids': []}, {'account_ids': ['a', 'a']},
    {'account_ids': [None]}, {'account_ids': [' ']}, {'from_date': 'bad'},
    {'to_date': '2020-01-01'}, {'page': 0}, {'page': True}, {'per_page': 501},
    {'per_page': 0}, {'cash_based': 'false'}, {'response_option': 1}, {'response_option': False},
])
def test_invalid_arguments_do_not_make_network_request(override):
    client = Mock()
    with pytest.raises(ValueError):
        Reports(client).account_transactions(**(ARGS | override))
    client.request.assert_not_called()


@pytest.mark.parametrize('option,key,value', [
    (0, 'from_date', '2026-01-01'), (0, 'to_date', '2026-01-02'),
    (0, 'cash_based', 'true'), (0, 'filter_by', 'TransactionDate.ThisMonth'),
    (0, 'page', 2), (0, 'rule', {}), (0, 'has_more_page', 'false'),
    (2, 'total', '66'), (2, 'total_pages', -1),
])
def test_rejects_ignored_scope_and_bad_pagination(option, key, value):
    client = Mock()
    payload = response(option)
    payload['page_context'][key] = value
    client.request.return_value = payload
    with pytest.raises(ValueError):
        Reports(client).account_transactions(**ARGS, response_option=option)


@pytest.mark.parametrize('payload', [None, {'code': 5}, {'code': 0},
    {'code': 0, 'page_context': {}}])
def test_rejects_failed_or_missing_responses(payload):
    client = Mock()
    client.request.return_value = payload
    with pytest.raises(ValueError):
        Reports(client).account_transactions(**ARGS)


def test_rejects_missing_transaction_groups():
    client = Mock()
    payload = response()
    del payload['account_transactions']
    client.request.return_value = payload
    with pytest.raises(ValueError, match='rows'):
        Reports(client).account_transactions(**ARGS)
