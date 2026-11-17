import json
from dataclasses import replace
from pathlib import Path
from fastapi import HTTPException
import pytest
from docx import Document
from openpyxl import Workbook
from app import api, ingest, retrieval
from app.config import settings


def setup_tenants(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','')
    config = replace(settings,tenants_root=tmp_path)
    monkeypatch.setattr(ingest,'settings',config)
    monkeypatch.setattr(retrieval,'settings',config)
    monkeypatch.setattr(api,'settings',config)
    monkeypatch.setenv('SUPPORT_API_TOKENS',json.dumps({'alpha-token':['alpha'],'beta-token':['beta']}))
    a = tmp_path/'alpha'; b = tmp_path/'beta'; a.mkdir(); b.mkdir()
    doc = Document(); doc.add_heading('Rate changes',1); doc.add_paragraph('Alpha approval is required before changing a loan rate.'); doc.save(a/'rate.docx')
    book = Workbook(); sheet = book.active; sheet.title='Fees'; sheet['A1']='Loan type';sheet['B1']='Fee';sheet['A2']='Demand';sheet['B2']='37.5%';sheet['C2']=10;sheet['D2']=5;sheet['E2']='=C2+D2';book.save(a/'fees.xlsx')
    (b/'secret.txt').write_text('Beta only secret policy',encoding='utf-8')
    for tenant in ('alpha','beta'):
        results = ingest.ingest_tenant(tenant)
        assert all(r['status']=='ready' for r in results)
    return a,b


def test_extraction_and_exact_excel_cell(tmp_path,monkeypatch):
    a,_ = setup_tenants(tmp_path,monkeypatch)
    docs = ingest.read_indexes('alpha')
    assert len(docs)==2
    assert any('Alpha approval' in c['content'] for d in docs for c in d['chunks'])
    rows = retrieval.query_excel('alpha','37.5%')
    assert rows[0]['sheet']=='Fees'
    assert any(c['coordinate']=='B2' and c['value']=='37.5%' for c in rows[0]['cells'])
    assert any(c['coordinate']=='E2' and c['formula']=='=C2+D2' and c['value'] is None for c in rows[0]['cells'])
    assert not retrieval.query_excel('beta','37.5%')
    assert not retrieval.document_section('beta', rows[0]['document_id'])
    assert not retrieval.keyword('alpha','Beta only secret')
    assert retrieval.keyword('beta','Beta only secret')
    calc = retrieval.calculate_excel('alpha',rows[0]['document_id'],'Fees',['C2','D2'],'difference')
    assert calc['result']==5 and calc['inputs'][0]['coordinate']=='C2'
    (a/'rate.docx').touch()
    assert len(ingest.read_indexes('alpha'))==1  # changed source cannot serve stale chunks
    assert ingest.ingest_file('alpha',a/'rate.docx')['status']=='ready'
    assert len(ingest.read_indexes('alpha'))==2
    replacement=Document(); replacement.add_heading('Rate changes',1); replacement.add_paragraph('Alpha revised rule.'); replacement.save(a/'rate.docx')
    assert not retrieval.keyword('alpha','Alpha approval')
    assert ingest.ingest_file('alpha',a/'rate.docx')['status']=='ready'
    current=next(d for d in ingest.read_indexes('alpha') if d['filename']=='rate.docx')
    assert current['version']==2
    assert 'Alpha revised rule' in current['chunks'][0]['content']
    assert not any('Alpha approval' in c['content'] for c in current['chunks'])


def test_authorization_and_session_scope(tmp_path,monkeypatch):
    setup_tenants(tmp_path,monkeypatch)
    api.SESSIONS.clear(); api.LOGS.clear()
    alpha = api.principal('Bearer alpha-token')
    beta = api.principal('Bearer beta-token')
    assert api.tenants(alpha)==[{'id':'alpha','name':'Alpha'}]
    with pytest.raises(HTTPException) as error:
        api.allowed('beta',alpha)
    assert error.value.status_code==403
    session=api.create_session(api.TenantBody(tenant_id='alpha'),alpha)['id']
    with pytest.raises(HTTPException) as error:
        api.session_row(session,beta)
    assert error.value.status_code==404
    with pytest.raises(HTTPException) as error:
        api.search('alpha',api.SearchBody(tenant_id='beta',query='rate'),alpha)
    assert error.value.status_code==400
    result=api.search('alpha',api.SearchBody(tenant_id='alpha',query='approval'),alpha)
    assert result and all(x['filename']=='rate.docx' for x in result)
    with pytest.raises(HTTPException) as error:
        api.send_message(session,api.MessageBody(content='rate?'),alpha)
    assert error.value.status_code==503


def test_malformed_token_configuration_returns_clear_error(monkeypatch):
    monkeypatch.setenv('SUPPORT_API_TOKENS', 'plain-token')
    with pytest.raises(HTTPException) as error:
        api.principal('Bearer plain-token')
    assert error.value.status_code == 503
    assert 'JSON object' in error.value.detail
