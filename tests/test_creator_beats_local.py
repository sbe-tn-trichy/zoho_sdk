import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from workflows.customer_local_store import open_store, sync_customers, stage_creator_beats_locally


def setup(tmp_path):
    db = open_store(tmp_path/'c.db', organization_id='org')
    rows=[{'contact_id': str(i), 'contact_type':'customer','contact_name':str(i),
           'status':'inactive' if i==3 else 'active', 'cf_beat':'Old',
           'custom_fields':[], 'custom_field_hash':{},
           'last_modified_time':'2026-10-27T10:00:00+0530'} for i in (1,2,3)]
    b=SimpleNamespace(contacts=SimpleNamespace(list=Mock(return_value={
        'contacts':rows,'page_context':{'has_more_page':False}})))
    sync_customers(db,b)
    return db


def row(cid, beat='New'):
    return {'Customer_Id':str(cid),'ID':str(cid+100),'Beat.Beat_Name':beat}


def test_stage_preserves_manual_and_skips_unassigned_missing_inactive(tmp_path):
    db=setup(tmp_path)
    db.execute("UPDATE customers SET cf_beat='Manual' WHERE contact_id='2'")
    db.commit()
    result=stage_creator_beats_locally(db,[row(1),row(2),row(3),row(4),row(5,'')])
    assert result['updated']==1
    assert len(result['preserved_local_changes'])==1
    assert result['missing']==['4'] and result['inactive']==1 and result['unassigned']==1
    r=db.execute("SELECT * FROM customers WHERE contact_id='1'").fetchone()
    assert r['cf_beat']=='New'
    assert json.loads(r['custom_fields'])[0]['value']=='New'
    assert json.loads(r['custom_field_hash'])['cf_beat']=='New'
    assert stage_creator_beats_locally(db,[row(1)])['unchanged']==1


def test_duplicate_rolls_back_whole_batch(tmp_path):
    db=setup(tmp_path)
    with pytest.raises(ValueError,match='duplicate'):
        stage_creator_beats_locally(db,[row(1),row(1)])
    assert db.execute("SELECT cf_beat FROM customers WHERE contact_id='1'").fetchone()[0]=='Old'
    assert db.execute("SELECT local_json FROM customer_snapshots WHERE contact_id='1'").fetchone()[0] is None


def test_creator_staging_after_constant_compaction(tmp_path):
    from workflows.customer_table import compact_customer_columns, customer_json
    db=setup(tmp_path)
    with db:
        compact_customer_columns(db)
    result=stage_creator_beats_locally(db,[row(1)])
    assert result['updated']==1
    assert customer_json(db,'1')['cf_beat']=='New'
    assert customer_json(db,'2')['cf_beat']=='Old'
