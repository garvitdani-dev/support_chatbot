# Tenant Support Assistant

A file based, tenant scoped support assistant for DOCX, XLSX, PDF, TXT, CSV, and Markdown files. The Spring Garden documents supplied with this project are in `data/tenants/spring-garden/Approaches/`. There is **no database**. Each tenant owns its source files and generated `.index/*.json` files in one folder.

## Repository assessment and implementation plan

The starting workspace contained only 12 Spring Garden documents under `Approaches/` and no application code, database, authentication, OpenAI integration, or tests. Ten active files are indexed; the two files in `Archives/` are excluded from current search. No existing component could be extended. The implementation therefore adds a FastAPI backend, file based extraction/indexing, hybrid retrieval, a Responses API tool loop, a browser UI, tests, and a retrieval benchmark.

The original retrieval failure described in the brief came from committing to one backend search result. This app gives the model tools to search again, inspect a complete section, query exact workbook cells, and check evidence before answering. The backend fixes tenant scope independently of model arguments.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- Set `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_EMBEDDING_MODEL` to models available to your account. No model name is fixed in source code.
- Set `SUPPORT_API_TOKENS` to a JSON object mapping each long random bearer token to its authorized tenant IDs. The example token is not suitable for deployment.
- Set `TENANTS_ROOT` if tenant folders live elsewhere.

Then index and start:

```bash
.venv/bin/python -m app.cli spring-garden
.venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, paste an authorized token, and choose a tenant. For another tenant, create `data/tenants/<tenant-id>/`, place its documents inside, add its ID to the appropriate token mapping, and run `.venv/bin/python -m app.cli <tenant-id>`. Tenant IDs use lowercase letters, digits, and hyphens. An authorized user can also upload files from the API and reindex a tenant. Re-run the CLI after editing files directly. Changed source files are excluded from search until reindexed, so stale content is not served. Uploads preserve the previous source in that tenant's `.history/` folder.

The initial index was generated without an API key, so it contains exact text and workbook data but no AI enrichment or embeddings. After setting the OpenAI variables, re-run the CLI; it detects the newly configured models and adds metadata and embeddings. The API returns 503 for chat until all three OpenAI variables are set. Searches and workbook queries work without them.

## Data and retrieval

- DOCX: heading sections, paragraphs, tables, headers, and footers. Word page numbers are only available if reliably present; this parser does not infer them.
- XLSX: sheets, rows, exact cell coordinates, formulas, cached results, number formats, and hidden row flags. Missing cached formula results are labeled unavailable. Calculations use only validated numeric cached values.
- PDF: page text and page numbers. Image-only PDFs fail ingestion with an OCR-required message.
- TXT, CSV, Markdown: text indexing. `.xls` is currently unsupported.
- `.index` JSON includes source hash, version, chunks, cells, metadata, and optional embeddings. Keyword ranking uses local lexical scores; semantic ranking uses OpenAI embeddings when configured. Reciprocal rank fusion deduplicates results. An OpenAI reranker orders candidates when configured.
- OpenAI response storage is disabled (`store=False`); tool outputs and response items are replayed within each request. The Responses API loop offers hybrid, keyword, semantic, workbook, calculation, document structure, section, and related-document tools. It can call more tools up to configured limits. Final source IDs are checked against retrieved evidence, then a separate model call checks support and conflict. Retrieval traces record tool names, query arguments, result counts, source IDs, status, latency, and token use.

## API

All `/api` routes require `Authorization: Bearer <token>`; access is checked server side for each tenant. Sessions are also tied to the token that created them.

| Route | Purpose |
|---|---|
| `GET /api/tenants` | Authorized tenant choices |
| `GET /api/tenants/{tenant}/documents` | Indexed files and statuses |
| `GET /api/tenants/{tenant}/documents/{id}` | Document metadata and sections |
| `POST /api/tenants/{tenant}/ingest` | Reindex tenant folder |
| `POST /api/tenants/{tenant}/documents/upload` | Upload and index a supported file |
| `POST /api/tenants/{tenant}/documents/{id}/reprocess` | Force reprocessing |
| `GET /api/tenants/{tenant}/documents/{id}/download` | Download original source |
| `POST /api/tenants/{tenant}/search` | Tenant scoped hybrid search |
| `POST /api/sessions` | Create a tenant locked chat session |
| `GET /api/sessions?tenant_id=...` | List your sessions |
| `GET /api/sessions/{id}/messages` | Conversation history |
| `POST /api/sessions/{id}/messages` | Ask a question |
| `POST /api/sessions/{id}/feedback` | Submit feedback |
| `GET /api/retrieval/logs/{request_id}` | Inspect a request trace |

Chat body: `{"content":"What is the demand loan procedure?"}`. Search body: `{"tenant_id":"spring-garden","query":"prepayment penalty"}`. The path and body tenant IDs must match. The model never receives a tenant selector it can change.

## Tests and benchmark

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python eval/run_retrieval.py
```

The 50-case benchmark in `eval/retrieval_cases.json` checks whether the expected source document appears in the top five local results. It is a retrieval smoke test, not an answer correctness or citation accuracy score. The tests cover extraction, exact workbook cell provenance, tenant search isolation, token-bound sessions, stale index exclusion, and a mocked multi-step Responses tool loop.

## Deployment and limits

Run behind HTTPS and a trusted reverse proxy. Protect `.env`, tenant folders, and `.index` files with filesystem permissions; none should be served as static files. Use long random tokens and rotate them by editing `.env` and restarting. In-memory rate limits cap chat, upload, and ingest requests. The app is intended for one worker: chat history, feedback, rate counters, and traces are held in process memory and disappear on restart. The source documents and indexes persist on disk. Large collections will need a more scalable index implementation, while preserving the same tenant folder boundary.

Live OpenAI calls were not run in this workspace because no API key was present. Verify the configured model supports Responses API function calling and JSON output before production use. The implementation follows the [official OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling) and [embeddings reference](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create). Model answers, even when source checked, still need review for consequential loan servicing decisions.
