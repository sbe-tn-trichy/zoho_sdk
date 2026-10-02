"""AIS source comparison with explicit bases and unresolved identities."""
from __future__ import annotations
import csv
import json
import re
from collections import defaultdict, Counter
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict
from workflows.core.matching import to_finite_decimal
from .master import Master, validate_master
from .sources import BooksSnapshot

class ReportSheet(TypedDict):
    name: str
    headers: list[str]
    rows: list[list[Any]]
    note: str

class ReconciliationReport(TypedDict):
    notes: list[list[str]]
    sheets: list[ReportSheet]
    statistics: dict[str, Any]
    metadata: dict[str, Any]

def money(v):
    result = to_finite_decimal(0 if v in (None, '') else v, allow_commas=True)
    if result is None:
        raise ValueError(f'Invalid monetary amount: {v!r}')
    return result

def num(v):
    return float(money(v).quantize(Decimal('.01')))

def fy(d):
    y = int(d[:4])
    y -= int(d[5:7]) < 4
    return f'{y}-{str(y + 1)[2:]}'

def month(s):
    return datetime.strptime(s, '%b-%Y').strftime('%Y-%m')

def iso(s):
    return datetime.strptime(s, '%d/%m/%Y').strftime('%Y-%m-%d')

def norm(s):
    s = re.sub('\\bPVT\\b', 'PRIVATE', s.upper())
    s = re.sub('\\bP(?=\\s+LTD\\b)', 'PRIVATE', s)
    s = re.sub('\\bLTD\\b', 'LIMITED', s)
    s = re.sub('\\bHOSPITALS\\b', 'HOSPITAL', s)
    return re.sub('[^A-Z0-9]', '', s)

def source_name(s):
    return re.sub('\\s*\\([A-Z0-9]{10}\\)\\s*$', '', s)

def get_pan(s):
    v = re.findall('\\(([A-Z]{5}[0-9]{4}[A-Z])\\)', s)
    return v[-1] if v else ''

def gst_pan(s):
    return s[2:12] if re.fullmatch('[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]{3}', s or '') else ''

def sheet(n, headers, rows, note):
    return {'name': n, 'headers': headers, 'rows': rows, 'note': note}

def reconcile_ais(ais_master: Master, snapshot: BooksSnapshot, *, gstin: str, master_name: str='AIS master') -> ReconciliationReport:
    validate_master(ais_master)
    if not snapshot['metadata'].get('complete'):
        raise ValueError('Incomplete Books snapshot')
    if str(snapshot['data']['organization']['organization']['organization_id']) != snapshot['metadata']['organization_id']:
        raise ValueError('Snapshot organization response disagrees with metadata')
    prefixes = sorted((n.removesuffix(' GST purchases') for n in ais_master if n.endswith(' GST purchases')))

    def load(name):
        return snapshot['data'][name]
    master = ais_master
    contacts = load('contacts')
    locs = load('locations')
    accounts = load('accounts')
    contact_by_id = {x['contact_id']: x for x in contacts}
    acct = {x['account_id']: x['account_name'] for x in accounts}
    scope = {x['location_id'] for x in locs if x.get('tax_reg_no') == gstin}
    if not scope:
        raise ValueError('No Books locations match the master GSTIN')
    while True:
        expanded = scope | {x['location_id'] for x in locs if x.get('parent_location_id') in scope}
        if expanded == scope:
            break
        scope = expanded

    def in_scope(d):
        return (d.get('location_id') or d.get('branch_id')) in scope
    scope_names = {x['location_name'] for x in locs if x['location_id'] in scope}

    def ledger_scope(r):
        return (r.get('branch') or {}).get('location_name') in scope_names
    taxledger = load('input_tax_ledger')
    incomeledger = [r for r in load('tax_income_ledger') if acct[r['account_id']] in ['TDS Receivable', 'TCS Receivable', 'Advance Tax']]
    tax_by_tx = defaultdict(Decimal)
    tcs_by_tx = defaultdict(Decimal)
    for r in taxledger:
        if r['transaction_type'] in ['bill', 'credit_note_vendor']:
            target = tcs_by_tx if acct[r['account_id']] == 'TCS Receivable' else tax_by_tx
            target[r['transaction_id']] += money(r.get('debit')) - money(r.get('credit'))
    books = []
    purchase_buckets = defaultdict(list)
    for d in load('bills'):
        if d['status'] in ['void', 'draft'] or not in_scope(d):
            continue
        base = money(d['total']) + money(d.get('tds_total')) - tax_by_tx[d['bill_id']] - tcs_by_tx[d['bill_id']]
        pan = gst_pan(d.get('gst_no', '')) or contact_by_id.get(d['vendor_id'], {}).get('pan_no', '')
        posting = d.get('txn_value_date') or d['date']
        entry = {'kind': 'Bill' if d.get('entity_type', 'bill') == 'bill' else 'Supplier credit-note bill', 'id': d['bill_id'], 'number': d['bill_number'], 'supplier': d['vendor_name'], 'pan': pan, 'gstin': d.get('gst_no', ''), 'date': d['date'], 'posting': posting, 'base': num(base), 'gross': d['total'], 'gst': num(tax_by_tx[d['bill_id']]), 'tcs': num(tcs_by_tx[d['bill_id']]), 'tds': d.get('tds_total', 0), 'location': d['location_name'], 'basis': 'Gross + TDS - input GST - TCS; rounding included'}
        books.append(entry)
        purchase_buckets[pan, d['date'][:7]].append(entry)
    for d in load('vendor_credits'):
        if d['status'] in ['void', 'draft'] or not in_scope(d):
            continue
        contact = contact_by_id.get(d['vendor_id'], {})
        pan = contact.get('pan_no') or gst_pan(contact.get('gst_no', ''))
        gst_credit = money(d['total']) - money(d['item_total_without_tax']) > Decimal('.01')
        entry = {'kind': 'GST vendor credit' if gst_credit else 'Commercial vendor credit', 'id': d['vendor_credit_id'], 'number': d['vendor_credit_number'], 'supplier': d['vendor_name'], 'pan': pan, 'gstin': contact.get('gst_no', ''), 'date': d['date'], 'posting': d['date'], 'base': -num(d['item_total_without_tax']), 'gross': -num(d['total']), 'gst': -num(money(d['total']) - money(d['item_total_without_tax'])), 'tcs': 0, 'tds': 0, 'location': d['location_name'], 'basis': 'Negative line-item value before GST; commercial credits excluded from GST net'}
        books.append(entry)
        purchase_buckets[pan, d['date'][:7]].append(entry)
    for d in load('expenses'):
        if d['status'] in ['void', 'draft'] or not in_scope(d):
            continue
        if money(d['total']) - money(d.get('total_without_tax')) <= 0:
            continue
        contact = contact_by_id.get(d.get('vendor_id'), {})
        pan = contact.get('pan_no') or gst_pan(contact.get('gst_no', ''))
        if not pan:
            continue
        entry = {'kind': 'GST expense', 'id': d['expense_id'], 'number': d.get('reference_number', ''), 'supplier': d['vendor_name'], 'pan': pan, 'gstin': contact.get('gst_no', ''), 'date': d['date'], 'posting': d['date'], 'base': num(d['total_without_tax']), 'gross': d['total'], 'gst': num(money(d['total']) - money(d['total_without_tax'])), 'tcs': 0, 'tds': 0, 'location': d['location_name'], 'basis': 'Expense total_without_tax'}
        books.append(entry)
        purchase_buckets[pan, d['date'][:7]].append(entry)
    ais_buckets = defaultdict(list)
    inactive = []
    source_checks = []
    for prefix in prefixes:
        for r in master[prefix + ' GST purchases'][1:]:
            c = r['cells']
            if c['H'] != 'Active':
                inactive.append([prefix + ' GST purchases', r['row'], c['B'], c['G'], c['H']])
                continue
            if c['E'] != gstin:
                raise ValueError('Master has another recipient GSTIN')
            pan = get_pan(c['B'])
            if not pan:
                detail_gst = re.search('\\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]{3})\\b', c.get('I', ''))
                pan = gst_pan(detail_gst.group(1)) if detail_gst else 'UNRESOLVED:' + source_name(c['B'])
            ais_buckets[pan, month(c['F'])].append({'value': c['G'], 'source': c['B'], 'ref': prefix + ' GST purchases!' + str(r['row']), 'serial': c['C'], 'detail': c.get('I', '')})
        for group, tab, valcol, statuscol in [('GST purchases', 'GST purchases', 'G', 'H'), ('GST turnover', 'GST sales', 'H', 'I')]:
            reported = sum((money(r['cells']['F']) for r in master[prefix + ' Source totals'][1:] if r['cells']['A'] == group))
            detail = sum((money(r['cells'][valcol]) for r in master[prefix + ' ' + tab][1:] if r['cells'][statuscol] == 'Active'))
            source_checks.append(['20' + prefix, group, num(reported), num(detail), num(detail - reported), 'Reported source total versus active detail sum'])
        for r in master[prefix + ' Source totals'][1:]:
            c = r['cells']
            if c['A'] not in ['Business receipts', 'Business expenses']:
                continue
            detail = [x['cells'] for x in master[prefix + ' TDS TCS'][1:] if x['cells']['D'] == c['G'] and x['cells']['A'] == c['A'] and (x['cells']['B'] == c['B']) and (x['cells']['L'] == 'Active')]
            source_checks.append(['20' + prefix, c['B'] + ' ' + source_name(c['D']), c['F'], num(sum((money(x['H']) for x in detail))), num(sum((money(x['H']) for x in detail)) - money(c['F'])), 'Source serial ' + str(c['G']) + '; active detail only'])
    posting_buckets = defaultdict(Decimal)
    for entry in books:
        if entry['kind'] in ['Bill', 'GST expense', 'GST vendor credit']:
            posting_buckets[entry['pan'], entry['posting'][:7]] += money(entry['base'])
    purchase_rows = []
    missing = []
    differences = []
    unresolved_rows = []
    annual = defaultdict(lambda: {'ais': Decimal(), 'books': Decimal(), 'name': '', 'missing': 0, 'diff': 0})
    for (pan, period), ais in sorted(ais_buckets.items(), key=lambda x: (x[0][1], x[1][0]['source'])):
        docs = purchase_buckets.get((pan, period), [])
        av = sum((money(x['value']) for x in ais))
        bv = sum((money(x['base']) for x in docs if x['kind'] in ['Bill', 'GST expense', 'GST vendor credit']))
        bills = sum((money(x['base']) for x in docs if x['kind'] == 'Bill'))
        credits = sum((money(x['base']) for x in docs if x['kind'] == 'GST vendor credit'))
        expenses = sum((money(x['base']) for x in docs if x['kind'] == 'GST expense'))
        commercial = sum((money(x['base']) for x in docs if x['kind'] == 'Commercial vendor credit'))
        posting = posting_buckets[pan, period]
        invoice = bills + expenses
        threshold = Decimal(max(1, len(ais)))
        name = source_name(ais[0]['source'])
        delta = bv - av
        no_purchase = not any((x['kind'] in ['Bill', 'GST expense'] and x['base'] > 0 for x in docs))
        unresolved = pan.startswith('UNRESOLVED:')
        if unresolved:
            status = 'Supplier identity incomplete'
        elif abs(delta) <= threshold:
            status = 'Matches GST net basis'
        elif no_purchase and av > 0:
            status = 'No Books purchase in month'
        elif abs(posting - av) <= Decimal(max(1, len(ais))):
            status = 'Posting date difference'
        else:
            status = 'Amount difference - review basis'
        refs = '; '.join((x['ref'] for x in ais))
        other_bills = sum((money(x['base']) for x in docs if x['kind'] == 'Supplier credit-note bill'))
        purchase_rows.append([fy(period + '-01'), period, name, '' if unresolved else pan, num(av), None if unresolved else num(bills), None if unresolved else num(expenses), None if unresolved else num(credits), None if unresolved else num(bv), None if unresolved else num(delta), None if unresolved else num(posting), len(docs), status, refs, None if unresolved else num(commercial), None if unresolved else num(invoice), None if unresolved else num(invoice - av), None if unresolved else num(other_bills)])
        if unresolved:
            unresolved_rows.append(['Supplier mapping', fy(period + '-01'), period, name, num(av), None, None, 'AIS omits supplier PAN/GSTIN; cannot confirm Books identity', refs])
        elif status == 'No Books purchase in month':
            missing.append(['GST purchase', fy(period + '-01'), period, name, num(av), num(bv), num(delta), 'Supplier/month gap; AIS contains no invoice number', refs])
        elif status != 'Matches GST net basis':
            differences.append(['GST purchase', fy(period + '-01'), period, name, num(av), num(bv), num(delta), status, refs])
        k = (fy(period + '-01'), pan)
        annual[k]['ais'] += av
        annual[k]['books'] += bv
        annual[k]['name'] = name
        annual[k]['missing'] += status == 'No Books purchase in month'
        annual[k]['diff'] += status != 'Matches GST net basis'

    def find_contacts(source):
        pan = get_pan(source)
        if pan:
            return [c for c in contacts if (c.get('pan_no') or gst_pan(c.get('gst_no', ''))) == pan]
        n = norm(source_name(source))
        direct = [c for c in contacts if norm(c['contact_name']) == n or norm(c.get('company_name', '')) == n]
        pans = {c.get('pan_no') for c in direct if c.get('pan_no')}
        if len(pans) > 1:
            return []
        return [c for c in contacts if c in direct or c.get('pan_no') in pans]
    tax_rows = []
    taxdetail = []
    tax_groups = defaultdict(list)
    base_candidates = []
    payments = snapshot['data'].get('customer_payments', [])
    credit_index = defaultdict(list)
    payment_index = defaultdict(list)
    for x in books:
        credit_index[x['pan'], x['date']].append(x)
    for x in payments:
        payment_index[x.get('customer_id'), x['date']].append(x)
    for prefix in prefixes:
        for r in master[prefix + ' TDS TCS'][1:]:
            c = r['cells']
            date = iso(c['G'])
            tax = money(c.get('I')) + money(c.get('J'))
            taxdetail.append(['20' + prefix, c['B'], c['C'], date, c['H'], num(tax), c.get('K', 0), c['L'], prefix + ' TDS TCS!' + str(r['row'])])
            if c['L'] != 'Active':
                inactive.append([prefix + ' TDS TCS', r['row'], c['C'], c['H'], c['L']])
                continue
            tax_groups['20' + prefix, 'TCS' if c['B'].startswith('TCS') else 'TDS', c['C']].append(c)
            date = iso(c['G'])
            cs = find_contacts(c['C'])
            cids = {x['contact_id'] for x in cs}
            pans = {x.get('pan_no') for x in cs if x.get('pan_no')}
            candidates = []
            if c['B'] == 'TDS-194R':
                candidates = [x for pan in pans for x in credit_index[pan, date] if x['kind'] in ['GST vendor credit', 'Commercial vendor credit', 'Supplier credit-note bill'] and abs(abs(money(x['base'])) - money(c['H'])) <= 1]
            else:
                candidates = [{'number': x['payment_number'], 'id': x['payment_id'], 'base': x['amount'], 'basis': 'Customer payment amount; may differ from AIS reporting base'} for cid in cids for x in payment_index[cid, date] if True and abs(money(x['amount']) + money(x.get('tax_amount_withheld')) - money(c['H'])) <= 1 and in_scope(x)]
            base_candidates.append(['20' + prefix, c['B'], source_name(c['C']), date, c['H'], num(tax), len(candidates), '; '.join((x['number'] for x in candidates)), '; '.join((x['id'] for x in candidates)), 'Date/amount candidate - confirm source' if len(candidates) == 1 else 'Multiple candidates' if candidates else 'No exact base candidate; review timing / reporting basis', prefix + ' TDS TCS!' + str(r['row'])])
    unallocated = []
    for r in incomeledger:
        if acct[r['account_id']] in ['TDS Receivable', 'TCS Receivable'] and money(r.get('debit')) > 0 and ledger_scope(r) and (not r.get('contact_id')):
            unallocated.append(r)
    for (year, typ, source), rows in sorted(tax_groups.items()):
        cs = find_contacts(source)
        cids = {c['contact_id'] for c in cs}
        n = norm(source_name(source))
        selected = [r for r in incomeledger if acct[r['account_id']] == typ + ' Receivable' and fy(r['date']) == year and ledger_scope(r) and (r.get('contact_id') in cids or norm(r.get('transaction_details', '')) == n)]
        ais_tax = sum((money(x.get('I')) + money(x.get('J')) for x in rows))
        book_tax = sum((money(r.get('debit')) for r in selected))
        unsettled = sum((money(r.get('debit')) for r in unallocated if fy(r['date']) == year and acct[r['account_id']] == typ + ' Receivable'))
        status = 'Source mapping unresolved' if not cids else 'Within Rs 1' if abs(book_tax - ais_tax) <= 1 else 'Needs journal allocation' if unsettled else 'Tax credit difference'
        tax_rows.append([year, typ, source_name(source), '; '.join(sorted(set((x['B'] for x in rows)))), num(sum((money(x['H']) for x in rows))), num(ais_tax), num(book_tax), num(book_tax - ais_tax), num(unsettled), len(selected), status, '; '.join(sorted(cids))])
        if status != 'Within Rs 1':
            differences.append([typ + ' credit', year, 'Full FY', source_name(source), num(ais_tax), num(book_tax), num(book_tax - ais_tax), status, 'AIS active TDS/TCS; Books receivable debit postings'])
    bankledger = list({(r['account_id'], r['transaction_id'], r['date'], str(r.get('debit')), str(r.get('credit'))): r for r in load('bank_windows')}.values())
    used_candidates = set()
    account_types = {x['account_id']: x['account_type'] for x in accounts}
    payment_rows = []
    for tab, datecol, valcol in [('Tax payments', 'I', 'G'), ('Refunds', 'G', 'F')]:
        for row in master[tab][1:]:
            c = row['cells']
            date = iso(c[datecol])
            av = money(c[valcol])
            dt = datetime.fromisoformat(date)
            asset = [r for r in incomeledger if acct[r['account_id']] == 'Advance Tax' and abs((datetime.fromisoformat(r['date']) - dt).days) <= 7 and (abs(money(r.get('debit')) - av) <= 1) and ledger_scope(r)] if tab == 'Tax payments' else []
            side = 'debit' if tab == 'Refunds' else 'credit'
            cash = [r for r in bankledger if account_types[r['account_id']] == 'bank' and abs((datetime.fromisoformat(r['date']) - dt).days) <= 7 and (abs(money(r.get(side)) - av) <= 1) and (ledger_scope(r) or not (r.get('branch') or {}).get('location_name'))]
            candidates = asset or cash
            candidates = [r for r in candidates if (r['account_id'], r['transaction_id']) not in used_candidates]
            if candidates:
                nearest = min((abs((datetime.fromisoformat(r['date']) - dt).days) for r in candidates))
                candidates = [r for r in candidates if abs((datetime.fromisoformat(r['date']) - dt).days) == nearest]
            if len(candidates) == 1:
                used_candidates.add((candidates[0]['account_id'], candidates[0]['transaction_id']))
            amount_side = 'debit' if asset or tab == 'Refunds' else 'credit'
            bv = sum((money(r.get(amount_side)) for r in candidates))
            if len(candidates) > 1:
                status = 'Ambiguous candidates'
            elif candidates and candidates[0]['date'] != date:
                status = 'Date difference - amount candidate'
            elif candidates:
                status = 'Amount/date candidate' if asset or tab == 'Refunds' else 'Bank payment found; tax asset not found'
            else:
                status = 'No amount candidate within 7 days'
            payment_rows.append([tab, c['A'], c['C'], date, c.get('E', c.get('D', '')), num(av), num(bv) if len(candidates)==1 else None, num(bv - av) if len(candidates)==1 else None, status, '; '.join((r.get('entity_number', '') for r in candidates)), c.get('K', ''), '; '.join((acct[r['account_id']] for r in candidates)), '; '.join((r['date'] for r in candidates))])
            if not candidates:
                missing.append([tab, c['A'], date, c.get('K', 'Income-tax refund'), num(av), None, None, status, tab + '!' + str(row['row'])])
            elif status != 'Amount/date candidate':
                differences.append([tab, c['A'], date, c.get('K', 'Income-tax refund'), num(av), num(bv) if len(candidates)==1 else None, num(bv - av) if len(candidates)==1 else None, status, tab + '!' + str(row['row'])])
    sales_rows = []
    for prefix in prefixes:
        data = load('sales_' + prefix)
        sales_master = {datetime.strptime(r['cells']['F'], '%b-%Y').strftime('%Y-%m'): money(r['cells']['H']) for r in master[prefix + ' GST sales'][1:] if r['cells']['I'] == 'Active'}
        if {r['period'] for r in data[:-1]} != set(sales_master):
            raise ValueError('Snapshot sales periods differ from active master periods')
        for r in data[:-1]:
            av = sales_master[r['period']]
            bv = money(r['books_sales_total'])
            delta = bv - av
            sales_rows.append(['20' + prefix, r['period'], num(av), num(bv), num(delta), 'Within Rs 1' if abs(delta) <= 1 else 'Sales difference'])
        reported = next((r['cells']['F'] for r in master[prefix + ' Source totals'][1:] if r['cells']['A'] == 'GST turnover'))
        bv = float(data[-1]['books_sales_total'])
        sales_rows.append(['20' + prefix, 'Annual reported total', reported, bv, num(money(bv) - money(reported)), 'Within Rs 1' if abs(money(bv) - money(reported)) <= 1 else 'Sales difference'])
    notes = [['Master', master_name + '; AIS active entries only. Source row references retained.'], ['Books', 'Organization ' + snapshot['metadata']['organization_id'] + '; snapshot captured ' + snapshot['metadata']['captured_at'] + '; currency INR.'], ['GST scope', gstin + ' and its descendant Books locations; other registrations excluded.'], ['Purchase grouping', 'Supplier PAN and month; all supplier state GST registrations combined to avoid truncated AIS supplier GSTIN text.'], ['Purchase basis', 'AIS purchases are compared with ordinary bills + GST expenses - GST vendor credits before GST. Invoice-only values are supporting evidence and do not count as matches. A net match does not certify invoice completeness. AIS does not supply invoice numbers or define gross/taxable basis beyond its label. Amount differences require basis review.'], ['Bill reconstruction', 'Bill gross + TDS deducted - input GST - TCS receivable. Rounding and adjustments remain; tax-free / RCM purchases may require document detail review.'], ['Vendor credits', 'Tax-bearing vendor credits reduce GST purchase net. Zero-tax commercial scheme credits are shown separately and excluded from GST purchase net. Classification uses gross less line value; review document details for exceptional adjustments.'], ['Purchase dates', 'Main comparison uses supplier bill date; posting-date net also shown to identify accounting timing differences.'], ['Missing meaning', 'No recorded purchase for the supplier PAN and month in the scoped bill/expense/credit pool. AIS monthly totals cannot prove which invoice is missing.'], ['Tax credits', 'AIS tax deducted/collected compared to new debit postings in TDS/TCS Receivable by source and FY. Settlements and refund credits are not new tax credits. Unallocated journals are disclosed.'], ['Income amounts', 'TDS/TCS base amounts are not automatically invoice values or taxable income. AIS detail bases are retained; do not add them to GST turnover or GST purchases.'], ['Tolerance', 'Rs 1 for tax and sales; purchase monthly tolerance is Rs 1 per active AIS aggregate entry, minimum Rs 1.'], ['Tax/refund matching', 'Amount candidates searched within 7 days of AIS date across all Books bank accounts; tax payments also checked in Advance Tax. Closest date chosen; ambiguous candidates remain unresolved. Confirm narration/CIN. Tax year can differ from payment year.'], ['Source quality', 'AIS reported annual totals and monthly/detail sums are reconciled separately; discrepancies belong to the source workbook.'], ['Supplier identity', 'Five FY 2025ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“26 purchase rows for SULTAN AHAMED ABDUL RAHMAN MOHAMED ABDULLAH omit supplier PAN and GSTIN. Their Books mapping is unresolved, not proven missing.']]
    annual_rows = [[year, v['name'], '' if pan.startswith('UNRESOLVED:') else pan, num(v['ais']), None if pan.startswith('UNRESOLVED:') else num(v['books']), None if pan.startswith('UNRESOLVED:') else num(v['books'] - v['ais']), v['missing'], v['diff']] for (year, pan), v in sorted(annual.items())]
    evidence = [[x['kind'], x['date'], x['posting'], x['supplier'], x['pan'], x['gstin'], x['number'], x['base'], x['gross'], x['gst'], x['tds'], x['tcs'], x['location'], x['id'], x['basis']] for x in books]
    ledgerevidence = [[r['date'], acct[r['account_id']], r['transaction_type'], r.get('transaction_details', ''), r.get('entity_number', ''), num(r.get('debit')), num(r.get('credit')), r.get('contact_id', ''), (r.get('branch') or {}).get('location_name', ''), r['transaction_id']] for r in incomeledger]
    out = {'notes': notes, 'sheets': [sheet('Missing in Books', ['Category', 'FY', 'Period / date', 'Supplier / reference', 'AIS INR', 'Books INR', 'Books minus AIS', 'Finding', 'AIS source'], missing, 'These are gaps or unmatched candidates, not automatic posting instructions.'), sheet('Unresolved mappings', ['Category', 'FY', 'Period', 'Supplier', 'AIS INR', 'Books INR', 'Books minus AIS', 'Finding', 'AIS source'], unresolved_rows, 'Incomplete supplier identity is not proof of missing transactions.'), sheet('Differences', ['Category', 'FY', 'Period', 'Supplier', 'AIS INR', 'Books INR', 'Books minus AIS', 'Finding', 'Source'], differences, 'GST purchase values require gross/net and timing review. TDS/TCS compare tax credits, not income.'), sheet('Purchase monthly', ['FY', 'Month', 'AIS supplier', 'Supplier PAN', 'AIS INR', 'Bills before GST', 'GST expenses', 'GST vendor credits', 'Books net INR', 'Net minus AIS', 'Posting date net', 'Books documents', 'Finding', 'AIS rows', 'Commercial credits INR', 'Books invoice basis INR', 'Invoice basis minus AIS', 'Other supplier credit-note bills INR'], purchase_rows, 'Main comparison: bills + GST expenses - GST vendor credits before GST; invoice-only figures are supporting detail. Supplier credit-note bills excluded from ordinary invoices. PAN combines registrations.'), sheet('Supplier annual', ['FY', 'Supplier', 'PAN', 'AIS detail INR', 'Books net INR', 'Books minus AIS', 'Missing months', 'Months to review'], annual_rows, 'Annual sums cover AIS-reported supplier months only. Other Books months are retained in Books purchases.'), sheet('GST sales', ['FY', 'Period', 'AIS INR', 'Books Sales INR', 'Books minus AIS', 'Finding'], sales_rows, 'Scoped accrual P&L Sales account hierarchy; monthly and independent FY report totals reconciled.'), sheet('Tax credits', ['FY', 'Type', 'AIS source', 'Sections', 'AIS base INR', 'AIS tax INR', 'Books debit INR', 'Books minus AIS', 'Unallocated FY debit', 'Books postings', 'Finding', 'Matched contact IDs'], tax_rows, 'Unallocated journal debits cannot be assigned to an AIS source without journal evidence.'), sheet('AIS TDS TCS', ['FY', 'Section', 'AIS source', 'Payment / credit date', 'AIS base INR', 'AIS tax INR', 'Tax deposited INR', 'AIS status', 'AIS row'], taxdetail, 'All master rows retained. Inactive rows are excluded from the comparison.'), sheet('AIS base candidates', ['FY', 'Section', 'Source', 'Date', 'AIS base INR', 'AIS tax INR', 'Candidate count', 'Books document', 'Books ID', 'Finding', 'AIS row'], base_candidates, '194R bases checked against same-date vendor-credit base; other receipt bases against grossed-up customer payments. Unmatched bases are review items, not proven missing income. TCS expense bases use tax-credit reconciliation; payment basis is not equivalent to bill purchases.'), sheet('Tax payments refunds', ['Type', 'Statement FY', 'Tax FY', 'Date', 'Nature', 'AIS INR', 'Books candidate INR', 'Books minus AIS', 'Finding', 'Books reference', 'AIS CIN', 'Books account', 'Books date'], payment_rows, 'Amount search within 7 days across all bank accounts and Advance Tax; confirm narration / CIN.'), sheet('AIS source checks', ['FY', 'Group / source', 'AIS reported INR', 'Active detail INR', 'Detail minus reported', 'Basis'], source_checks, 'Shows discrepancies inside the master workbook; Books differences must not hide them.'), sheet('Books purchases', ['Type', 'Bill date', 'Posting date', 'Supplier', 'PAN', 'Supplier GSTIN', 'Document number', 'Before GST INR', 'Gross INR', 'GST INR', 'TDS INR', 'TCS INR', 'Location', 'Books ID', 'Amount basis'], evidence, 'Bills, GST-bearing expenses and vendor credits within the AIS GST registration; void/draft records excluded.'), sheet('Books tax ledger', ['Date', 'Account', 'Type', 'Details', 'Document number', 'Debit INR', 'Credit INR', 'Contact ID', 'Location', 'Transaction ID'], ledgerevidence, 'Only TDS/TCS Receivable and Advance Tax postings. Scope applied in comparisons.'), sheet('Excluded AIS rows', ['AIS sheet', 'Row', 'AIS source', 'Base INR', 'AIS status'], inactive, 'Inactive AIS rows are retained for audit and excluded from all calculated master totals.')], 'statistics': {'missing': len(missing), 'differences': len(differences), 'purchase_statuses': dict(Counter((x[12] for x in purchase_rows))), 'tax_statuses': dict(Counter((x[10] for x in tax_rows))), 'books_evidence': len(books), 'source_excluded': len(inactive), 'unresolved': len(unresolved_rows)}}
    for row in sales_rows:
        if row[5] == 'Sales difference':
            differences.append(['GST sales', row[0], row[1], 'Sales', row[2], row[3], row[4], row[5], 'AIS GST sales'])
    out['statistics']['differences'] = len(differences)
    out['metadata'] = snapshot['metadata']
    return out

def write_report(report: ReconciliationReport, output: Path | str) -> Path:
    """Write JSON, Excel-safe CSV tables and a Markdown summary."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'report_data.json'
    path.write_text(json.dumps(report, ensure_ascii=True, default=str), encoding='utf-8')
    for table in report['sheets']:
        target = directory / (table['name'].lower().replace(' ', '_') + '.csv')
        with target.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(table['headers'])
            for row in table['rows']:
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in row])
    stats = report['statistics']
    (directory / 'summary.md').write_text('# AIS comparison\n\nSnapshot: ' + report['metadata']['captured_at'] + '\n\nSupplier/month or payment gaps: ' + str(stats['missing']) + '\n\nDifferences requiring review: ' + str(stats['differences']) + '\n\nUnresolved mappings: ' + str(stats['unresolved']) + '\n\nBasis matches do not certify invoice completeness. See Notes and detailed CSV tables.\n', encoding='utf-8')
    return path
