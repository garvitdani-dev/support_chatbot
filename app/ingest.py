from __future__ import annotations
import hashlib
import json
import re
import uuid
from pathlib import Path
from threading import RLock
from typing import Iterator
from .config import settings

SUPPORTED = {'.docx', '.xlsx', '.pdf', '.txt', '.md', '.csv'}
TENANT_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')

def validate_tenant(tenant: str) -> str:
    if not TENANT_PATTERN.fullmatch(tenant):
        raise ValueError('Invalid tenant ID')
    return tenant

def tenant_dir(tenant: str) -> Path:
    return settings.tenants_root / validate_tenant(tenant)

def iter_files(tenant: str) -> Iterator[Path]:
    base = tenant_dir(tenant)
    if not base.is_dir():
        raise ValueError('Unknown tenant')
    for path in sorted(base.rglob('*')):
        if path.is_file() and path.suffix.lower() in SUPPORTED and not any(part.lower() in {'archives','.history','.index'} for part in path.relative_to(base).parts):
            yield path

def _docx(path: Path):
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(path)
    sections = []
    heading = path.stem
    paragraphs = []
    def flush():
        if paragraphs:
            sections.append((heading, 'section', '\n'.join(paragraphs), {}))
            paragraphs.clear()
    for el in doc.element.body.iterchildren():
        if el.tag == qn('w:p'):
            from docx.text.paragraph import Paragraph
            p = Paragraph(el, doc)
            value = p.text.strip()
            if not value:
                continue
            if p.style and p.style.name.lower().startswith('heading'):
                flush()
                heading = value
            else:
                paragraphs.append(value)
        elif el.tag == qn('w:tbl'):
            from docx.table import Table
            table = Table(el, doc)
            rows = [' | '.join(c.text.replace('\n', '; ').strip() for c in row.cells) for row in table.rows]
            paragraphs.append('Table:\n' + '\n'.join(rows))
    flush()
    for section in doc.sections:
        for label, content in [('header', section.header), ('footer', section.footer)]:
            value = '\n'.join(p.text for p in content.paragraphs if p.text.strip())
            if value:
                sections.append((label, label, value, {}))
    return sections, []

def _xlsx(path: Path):
    from openpyxl import load_workbook
    formulas = load_workbook(path, data_only=False, read_only=False)
    cached = load_workbook(path, data_only=True, read_only=False)
    sections, cells = [], []
    for ws in formulas.worksheets:
        cache = cached[ws.title]
        for row in ws.iter_rows():
            values = []
            for cell in row:
                if cell.value is None:
                    continue
                formula = str(cell.value) if cell.data_type == 'f' else None
                actual = cache[cell.coordinate].value if formula else cell.value
                value = None if actual is None else str(actual)
                cells.append((ws.title, cell.coordinate, cell.row, cell.column, value, formula, cell.number_format))
                display = value if value is not None else '[formula result unavailable]'
                values.append(f'{cell.coordinate}={display}' + (f' (formula {formula})' if formula else ''))
            if values:
                sections.append((f'{ws.title}!{row[0].row}', 'spreadsheet_row', ' | '.join(values),
                                 {'sheet': ws.title, 'row': row[0].row, 'hidden': bool(ws.row_dimensions[row[0].row].hidden)}))
        for merged in ws.merged_cells.ranges:
            sections.append((ws.title, 'merged_range', f'Merged range {merged}: {ws[str(merged).split(":")[0]].value}', {'sheet': ws.title}))
    return sections, cells

def _pdf(path: Path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    sections = []
    for page_no, page in enumerate(reader.pages, 1):
        value = page.extract_text(extraction_mode='layout').strip()
        if value:
            sections.append((f'page {page_no}', 'page', value, {'page': page_no}))
    if not sections:
        raise ValueError('PDF has no extractable text; OCR is required')
    return sections, []

def extract(path: Path):
    suffix = path.suffix.lower()
    if suffix == '.docx': return _docx(path)
    if suffix == '.xlsx': return _xlsx(path)
    if suffix == '.pdf': return _pdf(path)
    if suffix in {'.txt', '.md', '.csv'}:
        return [(path.stem, 'text', path.read_text(encoding='utf-8-sig'), {})], []
    raise ValueError(f'Unsupported file type: {suffix}')

def _split(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ''
    for line in text.splitlines():
        if len(current) + len(line) > limit and current:
            parts.append(current.strip())
            current = ''
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current += line + '\n'
    if current.strip(): parts.append(current.strip())
    return parts

def _client():
    from openai import OpenAI
    return OpenAI(timeout=settings.timeout, max_retries=2)

def enrich(path: Path, sample: str) -> dict:
    base = {'title': path.stem, 'type': path.suffix.lower().lstrip('.')}
    if not settings.ai_ready:
        return base
    try:
        response = _client().responses.create(
            model=settings.openai_model,
            instructions='Describe this document for search indexing. Return JSON with summary and topics (list of strings). Do not infer business facts beyond supplied text.',
            input=f'JSON metadata task. Filename: {path.name}\nExtract:\n{sample[:6000]}',
            text={'format': {'type': 'json_object'}}, max_output_tokens=800, store=False)
        base.update(json.loads(response.output_text))
    except Exception as exc:
        base['enrichment_error'] = type(exc).__name__
    return base

def _embed(contents: list[str]) -> list[list[float] | None]:
    if not settings.ai_ready:
        return [None] * len(contents)
    result = []
    client = _client()
    for start in range(0, len(contents), 64):
        batch = contents[start:start + 64]
        response = client.embeddings.create(model=settings.embedding_model, input=batch)
        result.extend(item.embedding for item in sorted(response.data, key=lambda x: x.index))
    return result

def index_path(tenant: str, relative: str) -> Path:
    key = hashlib.sha256(relative.encode()).hexdigest()
    return tenant_dir(tenant) / '.index' / f'{key}.json'

_INDEX_CACHE: dict[str, tuple[tuple, list[dict]]] = {}
_INDEX_LOCK = RLock()

def read_indexes(tenant: str, include_failed: bool = False) -> list[dict]:
    base = tenant_dir(tenant)
    if not base.is_dir(): return []
    paths = sorted((base / '.index').glob('*.json'))
    signature = tuple((p.name,p.stat().st_mtime_ns,p.stat().st_size) for p in paths)
    key = str(base.resolve())
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached and cached[0] == signature:
            all_indexes = cached[1]
        else:
            all_indexes = []
            for path in paths:
                try:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    if data.get('tenant_id') == tenant:
                        all_indexes.append(data)
                except (ValueError,KeyError,OSError):
                    continue
            _INDEX_CACHE[key] = (signature, all_indexes)
    output = []
    for data in all_indexes:
        try:
            source = (base / data['relative_path']).resolve()
            if source.is_relative_to(base.resolve()) and source.is_file() and (include_failed or data['status'] == 'ready') and source.stat().st_mtime_ns == data.get('source_mtime_ns') and source.stat().st_size == data.get('source_size'):
                output.append(data)
        except (ValueError,KeyError,OSError):
            continue
    return output

def ingest_file(tenant: str, path: Path, force: bool = False) -> dict:
    base = tenant_dir(tenant).resolve()
    path = path.resolve()
    if not path.is_relative_to(base) or path.suffix.lower() not in SUPPORTED:
        raise ValueError('File outside tenant folder or unsupported')
    if path.stat().st_size > settings.max_upload_bytes:
        raise ValueError('File exceeds upload size limit')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    relative = str(path.relative_to(base))
    target = index_path(tenant,relative)
    old = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else None
    if old and old['sha256'] == digest and old['status'] == 'ready' and old.get('source_mtime_ns') == path.stat().st_mtime_ns and old.get('source_size') == path.stat().st_size and old.get('embedding_model') == (settings.embedding_model if settings.ai_ready else None) and old.get('enrichment_model') == (settings.openai_model if settings.ai_ready else None) and not force:
        return {'file':relative,'status':'unchanged','chunks':0}
    from datetime import datetime, timezone
    version = (old['version'] + 1) if old and old['sha256'] != digest else (old['version'] if old else 1)
    document_id = hashlib.sha256((tenant + '/' + relative).encode()).hexdigest()[:24]
    data = {'document_id':document_id,'tenant_id':tenant,'relative_path':relative,
            'filename':path.name,'sha256':digest,'version':version,'source_mtime_ns':path.stat().st_mtime_ns,'source_size':path.stat().st_size,'embedding_model':settings.embedding_model if settings.ai_ready else None,'enrichment_model':settings.openai_model if settings.ai_ready else None,'indexed_at':datetime.now(timezone.utc).isoformat()}
    try:
        sections, cells = extract(path)
        if not sections:
            raise ValueError('No extractable content')
        metadata = enrich(path, '\n'.join(x[2] for x in sections[:8]))
        pieces = [(location,kind,part,extra) for location,kind,content,extra in sections for part in _split(content) if part]
        vectors = _embed([p[2] for p in pieces])
        chunks = []
        for i,((location,kind,content,extra),vector) in enumerate(zip(pieces,vectors)):
            chunks.append({'chunk_id':hashlib.sha256(f'{document_id}:{i}:{content}'.encode()).hexdigest()[:24],
                'document_id':document_id,'filename':path.name,'location':location,'content_type':kind,
                'content':content,'metadata':extra,'embedding':vector,'version':version})
        data.update({'status':'ready','metadata':metadata,'chunks':chunks,
                     'cells':[{'sheet':s,'coordinate':coord,'row':row,'column':col,'value':value,'formula':formula,'number_format':fmt}
                              for s,coord,row,col,value,formula,fmt in cells]})
        result = {'file':relative,'status':'ready','chunks':len(chunks),'cells':len(cells)}
    except Exception as exc:
        data.update({'status':'failed','error':str(exc),'metadata':{},'chunks':[],'cells':[]})
        result = {'file':relative,'status':'failed','error':str(exc)}
    target.parent.mkdir(parents=True,exist_ok=True)
    temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    temp.replace(target)
    return result

def ingest_tenant(tenant: str, force: bool = False) -> list[dict]:
    return [ingest_file(tenant,p,force) for p in iter_files(tenant)]
