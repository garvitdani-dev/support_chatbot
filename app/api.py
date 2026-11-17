from __future__ import annotations
import secrets
import time
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import ROOT, settings
from .ingest import SUPPORTED, ingest_file, ingest_tenant, tenant_dir, validate_tenant, read_indexes
from . import retrieval, agent

app = FastAPI(title='Tenant Support Assistant', version='0.1.0')
app.mount('/static', StaticFiles(directory=ROOT/'app/static'), name='static')
# Intentionally ephemeral: no chat or retrieval database is used.
LOCK = RLock()
SESSIONS: dict[str,dict] = {}
LOGS: dict[str,dict] = {}
RATE: dict[tuple[str,str],list[float]] = {}

def rate_limit(user: Principal, bucket: str, limit: int):
    current = time.monotonic()
    key = (user.token_id,bucket)
    with LOCK:
        recent = [x for x in RATE.get(key,[]) if current-x<60]
        if len(recent)>=limit: raise HTTPException(429,'Rate limit exceeded; retry in one minute')
        recent.append(current)
        RATE[key] = recent

def now(): return datetime.now(timezone.utc).isoformat()

@app.get('/')
def home(): return FileResponse(ROOT/'app/static/index.html')

class Principal(BaseModel):
    tenants: list[str]
    token_id: str

def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Bearer token required')
    token = authorization[7:]
    try:
        token_map = settings.token_map
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    for configured,allowed in token_map.items():
        if secrets.compare_digest(token,configured): return Principal(tenants=allowed,token_id=hashlib.sha256(token.encode()).hexdigest())
    raise HTTPException(401,'Invalid token')

def allowed(tenant: str, user: Principal):
    try: validate_tenant(tenant)
    except ValueError: raise HTTPException(400,'Invalid tenant')
    if tenant not in user.tenants or not tenant_dir(tenant).is_dir():
        raise HTTPException(403,'Tenant not available')

class TenantBody(BaseModel): tenant_id: str
class SearchBody(TenantBody): query: str = Field(min_length=1,max_length=500)
class MessageBody(BaseModel): content: str = Field(min_length=1,max_length=4000)
class FeedbackBody(BaseModel):
    note: str = Field(max_length=1000)
    rating: str = Field(pattern='^(incorrect|incomplete|helpful)$')

@app.get('/api/tenants')
def tenants(user: Principal = Depends(principal)):
    return [{'id':t,'name':t.replace('-',' ').title()} for t in user.tenants if tenant_dir(t).is_dir()]

@app.get('/api/tenants/{tenant}/documents')
def documents(tenant: str,user: Principal = Depends(principal)):
    allowed(tenant,user)
    return [{k:d[k] for k in ('document_id','filename','relative_path','version','status','indexed_at')} for d in read_indexes(tenant,include_failed=True)]

@app.post('/api/tenants/{tenant}/ingest')
def ingest(tenant: str,user: Principal = Depends(principal)):
    allowed(tenant,user)
    rate_limit(user,'ingest',10)
    return ingest_tenant(tenant)

@app.get('/api/tenants/{tenant}/documents/{document_id}')
def document_detail(tenant: str,document_id: str,user: Principal = Depends(principal)):
    allowed(tenant,user)
    doc = next((d for d in read_indexes(tenant,include_failed=True) if d['document_id']==document_id),None)
    if not doc: raise HTTPException(404,'Document not found')
    return {k:v for k,v in doc.items() if k not in {'chunks','cells'}} | {'sections':list(dict.fromkeys(c['location'] for c in doc['chunks']))[:300]}

@app.post('/api/tenants/{tenant}/documents/upload')
async def upload(tenant: str,file: UploadFile = File(...),user: Principal = Depends(principal)):
    allowed(tenant,user)
    rate_limit(user,'upload',10)
    name = Path(file.filename or '').name
    if not name or name.startswith('.') or Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400,'Unsupported filename or file type')
    data = await file.read(settings.max_upload_bytes+1)
    if len(data)>settings.max_upload_bytes: raise HTTPException(413,'File too large')
    path = tenant_dir(tenant)/name
    if path.exists():
        history = tenant_dir(tenant)/'.history'
        history.mkdir(exist_ok=True)
        path.replace(history/f'{uuid.uuid4()}-{name}')
    temp = tenant_dir(tenant)/f'.upload-{uuid.uuid4()}'
    temp.write_bytes(data)
    temp.replace(path)
    return ingest_file(tenant,path)

@app.post('/api/tenants/{tenant}/documents/{document_id}/reprocess')
def reprocess(tenant: str,document_id: str,user: Principal = Depends(principal)):
    allowed(tenant,user)
    doc = next((d for d in read_indexes(tenant,include_failed=True) if d['document_id']==document_id),None)
    if not doc: raise HTTPException(404,'Document not found')
    return ingest_file(tenant,tenant_dir(tenant)/doc['relative_path'],True)

@app.get('/api/tenants/{tenant}/documents/{document_id}/download')
def download(tenant: str,document_id: str,user: Principal = Depends(principal)):
    allowed(tenant,user)
    doc = next((d for d in read_indexes(tenant) if d['document_id']==document_id),None)
    if not doc: raise HTTPException(404,'Document not found')
    path = (tenant_dir(tenant)/doc['relative_path']).resolve()
    if not path.is_relative_to(tenant_dir(tenant).resolve()) or not path.is_file(): raise HTTPException(404,'File not found')
    return FileResponse(path,filename=doc['filename'])

@app.post('/api/tenants/{tenant}/search')
def search(tenant: str,body: SearchBody,user: Principal = Depends(principal)):
    allowed(tenant,user)
    if body.tenant_id!=tenant: raise HTTPException(400,'Tenant mismatch')
    rate_limit(user,'search',60)
    return retrieval.hybrid(tenant,body.query)

@app.post('/api/sessions')
def create_session(body: TenantBody,user: Principal = Depends(principal)):
    allowed(body.tenant_id,user)
    item = {'id':str(uuid.uuid4()),'tenant_id':body.tenant_id,'created_at':now(),'messages':[],'token_id':user.token_id}
    with LOCK: SESSIONS[item['id']] = item
    return {k:item[k] for k in ('id','tenant_id','created_at')}

def session_row(session_id: str,user: Principal):
    with LOCK: row = SESSIONS.get(session_id)
    if not row or row['tenant_id'] not in user.tenants or row['token_id']!=user.token_id: raise HTTPException(404,'Session not found')
    return row

@app.get('/api/sessions')
def sessions(tenant_id: str,user: Principal = Depends(principal)):
    allowed(tenant_id,user)
    with LOCK:
        return [{k:s[k] for k in ('id','tenant_id','created_at')} for s in SESSIONS.values() if s['tenant_id']==tenant_id and s['token_id']==user.token_id][::-1][:50]

@app.get('/api/sessions/{session_id}/messages')
def messages(session_id: str,user: Principal = Depends(principal)):
    row = session_row(session_id,user)
    with LOCK: return list(row['messages'])

@app.post('/api/sessions/{session_id}/messages')
def send_message(session_id: str,body: MessageBody,user: Principal = Depends(principal)):
    row = session_row(session_id,user)
    rate_limit(user,'chat',30)
    with LOCK: history = list(row['messages'][-8:])
    try: result = agent.answer(row['tenant_id'],session_id,body.content,history)
    except RuntimeError as exc: raise HTTPException(503,str(exc))
    except Exception as exc: raise HTTPException(502,f'Answer service failed: {type(exc).__name__}')
    trace = result.pop('trace')
    with LOCK:
        row['messages'].append({'role':'user','content':body.content,'created_at':now()})
        row['messages'].append({'role':'assistant','content':result['answer'],'sources':result['sources'],
                                'status':result['status'],'created_at':now()})
        LOGS[result['request_id']] = trace
    return result

@app.post('/api/sessions/{session_id}/feedback')
def feedback(session_id: str,body: FeedbackBody,user: Principal = Depends(principal)):
    session_row(session_id,user)
    with LOCK: LOGS[str(uuid.uuid4())] = {'session_id':session_id,'feedback':body.model_dump(),'created_at':now()}
    return {'ok':True}

@app.get('/api/retrieval/logs/{request_id}')
def log(request_id: str,user: Principal = Depends(principal)):
    with LOCK: row = LOGS.get(request_id)
    if not row: raise HTTPException(404,'Log not found')
    session = row.get('session_id')
    if session: session_row(session,user)
    elif row.get('tenant_id') not in user.tenants: raise HTTPException(404,'Log not found')
    return row
