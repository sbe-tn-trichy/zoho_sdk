import pytest
from workflows.gst_monthly import month_bounds, check_monthly_gst


def report(month, cash=20):
    first,last = month_bounds(2024,month)
    return {'code':0,'page_context':{'from_date':first,'to_date':last,'cash_based':'false'},'trialbalance':{'accounts':[
        {'name':name,'values':[{'net_debit':debit,'net_credit':credit}]} for tax in ('CGST','SGST','IGST','CESS')
        for name,debit,credit in [(f'Input {tax}',100,0),(f'Output {tax}',0,120),(f'Cash Ledger : {tax} Tax',cash,cash)]]}}


def test_next_month_gross_debits_not_zero_net_cash():
    rows = check_monthly_gst(report(4),report(5))
    assert all(c.difference == 0 and c.next_month_cash_debits == 20 for c in rows)


def test_mismatch():
    assert check_monthly_gst(report(4),report(5,25))[0].difference == 5


def test_wrong_payment_month_rejected():
    with pytest.raises(ValueError): check_monthly_gst(report(4),report(6))


def test_missing_account_rejected():
    data=report(4); data['trialbalance']['accounts'].pop()
    with pytest.raises(ValueError): check_monthly_gst(data,report(5))


def test_leap_month():
    assert month_bounds(2024,2)[1]=='2024-02-29'
