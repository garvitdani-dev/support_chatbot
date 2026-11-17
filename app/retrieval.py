from __future__ import annotations
import math
import re
from collections import Counter
from .config import settings
from .ingest import read_indexes

TOKEN = re.compile(r'[\w]+', re.UNICODE)
STOPWORDS = {'the','a','an','is','are','was','were','what','where','how','which','who','when','does','do','for','of','on','in','to','and','or','with','by','be','can','this','that','it'}

def _chunks(tenant: str, document_id: str | None = None):
    return [chunk for doc in read_indexes(tenant) if not document_id or doc['document_id'] == document_id for chunk in doc['chunks']]

def _public(item: dict):
    return {k:v for k,v in item.items() if k != 'embedding'}

def keyword(tenant: str, query: str, limit: int | None = None, document_id: str | None = None):
    words = [w.lower() for w in TOKEN.findall(query) if len(w)>1 and w.lower() not in STOPWORDS][:15]
    if not words: return []
    docs = _chunks(tenant,document_id)
    n = len(docs)
    df = Counter()
    for chunk in docs:
        df.update(set(w.lower() for w in TOKEN.findall(chunk['content'])))
    scored = []
    for chunk in docs:
        content = chunk['content'].lower()
        counts = Counter(TOKEN.findall(content))
        length = max(1,sum(counts.values()))
        score = 0.0
        for word in words:
            tf = counts[word]
            if tf:
                idf = math.log(1 + (n - df[word] + .5)/(df[word] + .5))
                score += idf * tf * 2.2 / (tf + 1.2*(.25+.75*length/200))
            if word in chunk['filename'].lower(): score += 3.0
            if word in chunk['location'].lower(): score += 1.0
        if query.lower() in content: score += 5.0
        if score > 0: scored.append({**_public(chunk),'method':'keyword','score':round(score,5)})
    return sorted(scored,key=lambda c:c['score'],reverse=True)[:min(limit or settings.top_k,50)]

def _cosine(a,b):
    if not a or not b or len(a)!=len(b): return 0.0
    return sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a))*math.sqrt(sum(y*y for y in b))+1e-12)

def semantic(tenant: str, query: str, limit: int | None = None, document_id: str | None = None):
    if not settings.ai_ready: return []
    indexed = [c for c in _chunks(tenant,document_id) if c.get('embedding')]
    if not indexed: return []
    from openai import OpenAI
    vector = OpenAI(timeout=settings.timeout,max_retries=2).embeddings.create(model=settings.embedding_model,input=query).data[0].embedding
    ranked = sorted(((_cosine(vector,c.get('embedding')),_public(c)) for c in indexed),
                    key=lambda pair:pair[0],reverse=True)
    return [{**c,'method':'semantic','score':round(score,5)} for score,c in ranked[:min(limit or settings.top_k,50)]]

def hybrid(tenant: str, query: str, limit: int | None = None, document_id: str | None = None):
    pools = [keyword(tenant,query,settings.top_k,document_id)]
    if settings.ai_ready: pools.append(semantic(tenant,query,settings.top_k,document_id))
    found = {}
    for pool in pools:
        for rank,item in enumerate(pool,1):
            key = item['chunk_id']
            if key not in found: found[key] = {**item,'methods':[],'fusion_score':0.0}
            found[key]['fusion_score'] += 1/(60+rank)
            found[key]['methods'].append(item['method'])
    return sorted(found.values(),key=lambda c:c['fusion_score'],reverse=True)[:min(limit or settings.rerank_k,50)]

def rerank(question: str, candidates: list[dict]) -> list[dict]:
    if not settings.ai_ready or len(candidates)<2: return candidates
    import json
    from openai import OpenAI
    prompt = {'question':question,'candidates':[{'id':c['chunk_id'],'text':c['content'][:900],'source':c['filename']} for c in candidates[:20]]}
    try:
        response = OpenAI(timeout=settings.timeout,max_retries=2).responses.create(
            model=settings.openai_model,
            instructions='Rank evidence by direct relevance. Return JSON {"ids": [candidate IDs in best-first order]}. Do not answer.',
            input='Return JSON ranking: '+json.dumps(prompt),text={'format':{'type':'json_object'}},max_output_tokens=400,store=False)
        ids = json.loads(response.output_text)['ids']
        order = {id_:i for i,id_ in enumerate(ids) if isinstance(id_,str)}
        return sorted(candidates,key=lambda c:order.get(c['chunk_id'],999))[:settings.rerank_k]
    except Exception: return candidates[:settings.rerank_k]

def query_excel(tenant: str, text: str, document_id: str | None = None, sheet: str | None = None,
                column: str | None = None, value: str | None = None, limit: int = 10):
    if len(text)>200 or (value and len(value)>200): raise ValueError('Query too long')
    if column and not re.fullmatch(r'[A-Z]{1,3}',column.upper()): raise ValueError('Invalid column')
    output = []
    for doc in read_indexes(tenant):
        if document_id and doc['document_id']!=document_id: continue
        rows = {}
        for cell in doc['cells']:
            if sheet and cell['sheet']!=sheet: continue
            rows.setdefault((cell['sheet'],cell['row']),[]).append(cell)
        for (sheet_name,row_number),cells in rows.items():
            terms = value or text
            if any(terms.lower() in str(c.get('value') or c.get('formula') or '').lower() and
                   (not column or c['coordinate'].startswith(column.upper())) for c in cells):
                output.append({'document_id':doc['document_id'],'filename':doc['filename'],'version':doc['version'],
                    'sheet':sheet_name,'row':row_number,'evidence_id':f"excel:{doc['document_id']}:{sheet_name}:{row_number}",
                    'cells':[{k:c[k] for k in ('coordinate','value','formula','number_format')} for c in cells]})
                if len(output)>=min(limit,30): return output
    return output

def document_structure(tenant: str, document_id: str | None = None):
    result = []
    for doc in read_indexes(tenant):
        if document_id and doc['document_id']!=document_id: continue
        result.append({'document_id':doc['document_id'],'filename':doc['filename'],'version':doc['version'],
            'metadata':doc['metadata'],'sections':list(dict.fromkeys(c['location'] for c in doc['chunks']))[:300]})
    return result

def document_section(tenant: str, document_id: str, location: str | None = None, max_chars: int = 12000):
    result = []; used = 0
    for c in _chunks(tenant,document_id):
        if location and c['location']!=location: continue
        if used+len(c['content'])>max_chars: break
        result.append(_public(c)); used += len(c['content'])
    return result

def related_documents(tenant: str, document_id: str, topic: str):
    doc = next((d for d in read_indexes(tenant) if d['document_id']==document_id),None)
    if not doc: return []
    return [c for c in hybrid(tenant,topic or doc['filename'],15) if c['document_id']!=document_id]

def calculate_excel(tenant: str, document_id: str, sheet: str, coordinates: list[str], operation: str):
    if operation not in {'sum','difference','product','quotient'} or not 1 <= len(coordinates) <= 10:
        raise ValueError('Unsupported calculation')
    if any(not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', c) for c in coordinates):
        raise ValueError('Invalid cell coordinate')
    doc = next((d for d in read_indexes(tenant) if d['document_id']==document_id),None)
    if not doc: raise ValueError('Document not found')
    found = {(c['sheet'],c['coordinate']):c for c in doc['cells']}
    cells = []
    for coord in coordinates:
        cell = found.get((sheet,coord))
        if not cell or cell['value'] is None:
            raise ValueError(f'No cached numeric value at {sheet}!{coord}')
        try: number = float(cell['value'])
        except ValueError: raise ValueError(f'Non numeric value at {sheet}!{coord}')
        cells.append((cell,number))
    values = [n for _,n in cells]
    if operation=='sum': result=sum(values)
    elif operation=='difference': result=values[0]-sum(values[1:])
    elif operation=='product': result=math.prod(values)
    else:
        if len(values)!=2 or values[1]==0: raise ValueError('Quotient requires two values and nonzero divisor')
        result=values[0]/values[1]
    return {'document_id':document_id,'filename':doc['filename'],'sheet':sheet,
            'operation':operation,'result':result,'inputs':[{'coordinate':c['coordinate'],'value':c['value'],'number_format':c['number_format']} for c,_ in cells],
            'evidence_id':f"calculation:{document_id}:{sheet}:{','.join(coordinates)}",'version':doc['version']}
