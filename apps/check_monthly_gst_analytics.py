"""Monthly GST comparison from Zoho Analytics accrual postings."""
import argparse
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
import json
try:
    from . import _bootstrap
except ImportError:
    import _bootstrap
from workflows.core.auth import get_analytics_client
from workflows.core.matching import parse_currency_amount
from workflows.core.checkpoint import write_atomic_json, atomic_text_writer
from workflows.audited_financials.reports import _firm_rule
from workflows.gst_monthly import check_monthly_gst, month_bounds


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start-month',default='2025-04')
    p.add_argument('--end-month',default='2026-03')
    p.add_argument('--firm',default='BD')
    p.add_argument('--output',type=Path,default=Path('output/monthly-gst-analytics-fy25-26'))
    args=p.parse_args()
    start,end=[datetime.strptime(x,'%Y-%m').date() for x in (args.start_month,args.end_month)]
    if start>end: raise ValueError('Start follows end')
    periods=[]; y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        periods.append((y,m)); y,m=(y+1,1) if m==12 else (y,m+1)
    months=periods+[(y,m)]; final=month_bounds(y,m)[1]
    scope=_firm_rule(args.firm,None)['columns'][0]
    ids=scope['value']
    if any(not x.isdigit() for x in ids): raise ValueError('Invalid configured location ID')
    scope_sql='T."Location ID" '+('NOT IN' if scope['comparator']=='not_in' else 'IN')+' ('+','.join(ids)+')'
    if scope['comparator']=='not_in': scope_sql='('+scope_sql+' OR T."Location ID" IS NULL)'
    cash_ids={'1094368000010597013','1094368000010597017','1094368000010597015'}
    names=[name for tax in ('CGST','SGST','IGST','CESS') for name in (f'Input {tax}',f'Output {tax}',f'Cash Ledger : {tax} Tax')]
    account_list=','.join("'"+n+"'" for n in names)
    sql=f'''SELECT YEAR(T."Transaction Date") AS "Year", MONTH(T."Transaction Date") AS "Month",
 A."Account Name" AS "Account", A."Account ID" AS "Account ID",
 SUM(T."Debit Amount") AS "Debit", SUM(T."Credit Amount") AS "Credit"
 FROM "Accrual Transactions (Zoho Books)" T JOIN "Accounts (Zoho Books)" A ON T."Account ID"=A."Account ID"
 WHERE T."Transaction Date">='{start.isoformat()}' AND T."Transaction Date"<='{final}'
 AND A."Account Name" IN ({account_list}) AND {scope_sql}
 GROUP BY YEAR(T."Transaction Date"), MONTH(T."Transaction Date"), A."Account Name", A."Account ID"'''
    api=get_analytics_client(); workspace='264324000000002043'
    catalog=api.queries.execute(workspace,f'SELECT "Account Name", "Account ID" FROM "Accounts (Zoho Books)" WHERE "Account Name" IN ({account_list})')
    known={}
    for c in catalog:
        n=c['Account Name']
        if n in known: raise ValueError('Ambiguous GST account: '+n)
        known[n]=str(c['Account ID'])
    if set(names)-known.keys(): raise ValueError('Missing GST account catalog entries')
    resolved={n:i for n,i in known.items() if i in cash_ids}
    if set(resolved.values())!=cash_ids or set(resolved)!={f'Cash Ledger : {tax} Tax' for tax in ('CGST','SGST','IGST')}:
        raise ValueError('Requested cash IDs do not match tax accounts: '+str(resolved))
    print('Cash accounts:',json.dumps(resolved))
    rows=api.queries.execute(workspace,sql)
    args.output.mkdir(parents=True,exist_ok=True)
    write_atomic_json(args.output/'monthly-postings.json',rows)
    with atomic_text_writer(args.output/'query.sql') as f: f.write(sql)
    reports={}
    for yy,mm in months:
        first,last=month_bounds(yy,mm)
        amounts={n:[Decimal(0),Decimal(0)] for n in names}
        for r in rows:
            if int(r['Year'])==yy and int(r['Month'])==mm:
                amounts[r['Account']][0]+=parse_currency_amount(r['Debit'] or 0)
                amounts[r['Account']][1]+=parse_currency_amount(r['Credit'] or 0)
        reports[(yy,mm)]={'code':0,'page_context':{'from_date':first,'to_date':last,'cash_based':'false'},'trialbalance':[
            {'name':n,'values':[{'net_debit':str(v[0]),'net_credit':str(v[1])}]} for n,v in amounts.items()]}
    lines=['# Monthly GST check — Zoho Analytics','',f'Firm {args.firm}; GST months {args.start_month} to {args.end_month}. Created {datetime.now().astimezone().isoformat(timespec="seconds")}.','',
        'GST month is compared with cash-tax ledger debits in the following month. Interest and late fees excluded. Gross cash debits are a payment proxy, not verified bank payments. Cross-head ITC, carried credits and adjustments can explain differences. Analytics reflects its latest sync. Missing monthly postings for known accounts are zero.', '',
        'Formula: combined Output CGST + SGST + IGST minus combined Input CGST + SGST + IGST. CESS excluded. Cash account IDs: '+', '.join(sorted(cash_ids)), '',
        '| GST month | Payment month | Output GST total | Input GST total | Output − Input | Cash-ledger total | Difference | Result |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    summary=[]
    for yy,mm in periods:
        ny,nm=(yy+1,1) if mm==12 else (yy,mm+1)
        checks=check_monthly_gst(reports[(yy,mm)],reports[(ny,nm)])
        checks=[c for c in checks if c.tax in ('CGST','SGST','IGST')]
        output=sum(c.output for c in checks); input_tax=sum(c.input for c in checks)
        net=output-input_tax; cash=sum(c.next_month_cash_debits for c in checks)
        lines.append(f'| {yy}-{mm:02d} | {ny}-{nm:02d} | {output:,.2f} | {input_tax:,.2f} | {net:,.2f} | {cash:,.2f} | {cash-net:,.2f} | {"Review" if abs(cash-net)>Decimal(".01") else "Match"} |')
        summary.append({'month':f'{yy}-{mm:02d}','net_gst':str(net),'cash':str(cash),'difference':str(cash-net)})
    with atomic_text_writer(args.output/'report.md') as f: f.write('\n'.join(lines)+'\n')
    print(json.dumps(summary)); print((args.output/'report.md').resolve())


if __name__=='__main__': main()
