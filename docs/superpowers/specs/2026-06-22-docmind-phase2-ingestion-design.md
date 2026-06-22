# YDG DocMind — Phase 2: Ingestion Core (Design Spec)

- **Date:** 2026-06-22
- **Status:** Approved design, ready for implementation planning
- **Builds on:** Phase 1 (Skeleton, merged to `main`). Parent spec:
  `2026-06-19-docmind-rag-chatbot-design.md` (§4 data model, §5 ingestion).
- **Goal:** Turn an uploaded document into searchable dense vectors: a user creates a
  knowledge base, uploads a file, and watches it move `queued → extracting → embedding →
  ready` via a live (polled) status indicator. Retrieval/chat is Phase 3.

---

## 1. Scope

**In scope:** knowledge-base CRUD (create/list/get, single-owner), file upload, an async
ingestion pipeline (extract → chunk → embed → index into Milvus), per-document status with
polled progress, and document delete.

**Out of scope (later phases):** retrieval / hybrid search / rerank / chat (Phase 3);
multimodal table/chart extraction (Phase 4 — nv-ingest runs in **text mode** here); rich
citation panel (Phase 5); sparse vectors / hybrid index (Phase 3, when retrieval needs them);
SSE progress streaming (deferred — see §9).

### Phase-2 decisions (locked during brainstorming)
| Question | Decision |
|---|---|
| Embedding | Real NVIDIA hosted NIM `llama-3.2-nv-embedqa` (user has/will get a key), behind an `Embedder` interface with a deterministic `StubEmbedder` for tests |
| Extraction | Stand up **nv-ingest now in text mode**, behind an `Extractor` interface; **no fallback extractor** — a contained spike (Task 1) proves it installs/extracts before the pipeline is built on it, and a spike failure is a blocker to resolve, not routed around |
| Milvus index | **Dense vectors only** now; sparse/hybrid deferred to Phase 3 |
| Progress | **Polling** (TanStack Query `refetchInterval`); SSE deferred to a later point (§9) |

---

## 2. Architecture & boundaries

New backend units, each with one responsibility and a well-defined interface so they are
independently testable and swappable later. All are transport-agnostic (no knowledge of HTTP,
React, or arq).

| Unit | File | Responsibility |
|---|---|---|
| `Extractor` (interface) | `api/app/ingest/extractor.py` | `extract(data: bytes, mime: str) -> list[TextSegment]` (text + page_no) |
| `NvIngestExtractor` | `api/app/ingest/nvingest_extractor.py` | nv-ingest in text mode; config-driven endpoints; **the only Extractor impl** |
| `Chunker` | `api/app/ingest/chunker.py` | `chunk(segments) -> list[Chunk]` (recursive, preserves page refs) |
| `Embedder` (interface) | `api/app/ingest/embedder.py` | `embed(texts: list[str]) -> list[list[float]]` |
| `NimEmbedder` | `api/app/ingest/nim_embedder.py` | calls `llama-3.2-nv-embedqa` (hosted NIM) |
| `StubEmbedder` | `api/app/ingest/embedder.py` | deterministic local vectors (tests, no key/network) |
| `VectorStore` | `api/app/ingest/vector_store.py` | Milvus wrapper: ensure collection (partition=kb_id), insert dense vectors |
| `IngestionService` | `api/app/ingest/service.py` | orchestrates the pipeline; drives `documents.status` |
| arq `worker` | `api/app/worker.py` | runs `ingest(document_id)` jobs off Redis |

**Dependency direction:** routes → `IngestionService`/repos → the four interfaces → models.
The worker and routes are thin shells over `IngestionService`.

### nv-ingest install risk (spike-first, no fallback)
nv-ingest's Python library is heavy and historically finicky to install (deps, image size).
Per the user's decision, nv-ingest is the **only** extractor — there is no `PlainExtractor`
fallback. To de-risk this, **Task 1 of the plan is a contained spike**: prove nv-ingest installs
in the worker image and extracts text from a sample PDF *before* building the pipeline on it.
The spike's outcome is recorded in the plan before dependent tasks proceed. If the spike cannot
be made to work cleanly in the container, that is a **blocker escalated to the user** — Phase 2
does not proceed on a substitute extractor. The `Extractor` interface still exists (clean
boundary + the seam Phase 4 swaps multimodal mode into), but it has exactly one implementation.

---

## 3. Data model (migration `0002`)

Extends Phase 1's `users`. Columns scoped to what Phase 2 uses; `table_html`/`image_uri` exist
now (nullable) so Phase 4 needs no further migration.

```
knowledge_bases  id PK, owner_id→users, name, description(null),
                 gen_model (default 'nim-llama'), created_at (tz, now())
documents        id PK, kb_id→knowledge_bases, filename, mime, size,
                 status (default 'queued'), page_count(null), error(null),
                 chunks_total (default 0), chunks_done (default 0), uploaded_at (tz, now())
                 # status ∈ queued|extracting|embedding|ready|failed
chunks           id PK, document_id→documents, kb_id, page_no, kind (default 'text'),
                 text, table_html(null), image_uri(null), milvus_pk(null, int8)
```

- `documents.status` + `chunks_done`/`chunks_total` ARE the progress signal the frontend polls.
- Ownership: every KB-scoped route checks `kb.owner_id == current_user.id`; mismatch → **404**
  (not 403 — don't leak existence).
- Original files: `./storage/{kb_id}/{document_id}/{filename}` (local volume, mounted into api +
  worker). Path derivable from IDs.

### Milvus collection
One collection `docmind_chunks`, **partitioned by `kb_id`**. Fields: `pk` (int64, autoid),
`kb_id` (int64), `document_id` (int64), `dense_vector` (float vector, dim from
`settings.embed_dim`), `text` (varchar). HNSW index on `dense_vector` (metric IP).
`VectorStore.ensure_collection()` is idempotent (create-if-absent + create partition-if-absent).

---

## 4. Ingestion pipeline

`IngestionService.ingest(document_id)`, executed by the arq worker:

```
1. load document row; read bytes from ./storage/{kb_id}/{document_id}/{filename}
2. status=extracting → Extractor.extract(bytes, mime) -> [TextSegment(text, page_no)]
   set page_count = max(page_no) (or segment count for non-paged formats)
3. status=embedding  → Chunker.chunk(segments) -> [Chunk(text, page_no)]; set chunks_total
   → Embedder.embed(batch of chunk texts) -> dense vectors (batched, default 64/req)
   incrementing chunks_done per batch
4. persist: insert chunk rows (Postgres) + VectorStore.insert(kb_id, doc_id, vectors, texts)
   -> write returned milvus_pk back onto each chunk row
5. status=ready (commit)
On ANY exception in 2-4: rollback partial work, status=failed, error=str(e)[:2000].
Per-document isolation: one failed document never blocks the queue or siblings.
```

Empty extraction (0 segments) is a clean `failed` with a clear error ("no extractable text"),
not a crash. Re-upload re-enqueues fresh.

---

## 5. API routes

All under `/api`, all require `current_user`, all KB-scoped routes enforce ownership (→404).

| Method · Path | Purpose |
|---|---|
| `POST /api/kbs` | create KB `{name, description?}` → KB |
| `GET /api/kbs` | list the caller's KBs |
| `GET /api/kbs/{kb_id}` | get one KB (owned) |
| `POST /api/kbs/{kb_id}/documents` | multipart upload: save bytes, create `documents` (queued), enqueue arq job, return row |
| `GET /api/kbs/{kb_id}/documents` | list docs with live `status`, `chunks_done/total`, `error` (polled) |
| `DELETE /api/documents/{document_id}` | delete doc: Postgres rows + Milvus entries (by document_id) + file |

Upload guardrails: allowed mime allowlist (pdf, docx, txt, md), max size from config (default
25 MB) → 413 over limit. Enqueue exactly one job per successful upload.

---

## 6. Frontend

The Phase-1 empty shell becomes functional. Add `react-router-dom`.

- **Home view** (`/`): grid of KB cards + a "New knowledge base" inline create form.
- **KB detail** (`/kb/:id`): file drop zone / picker (POSTs upload), and a document list. Each
  row shows a **status pill** (queued/extracting/embedding/ready/failed) and a thin progress bar
  driven by `chunks_done/chunks_total`. Failed rows show the error and a re-upload affordance.
- **Polling:** TanStack Query fetches `GET /api/kbs/{id}/documents` with `refetchInterval` ~2000ms
  **only while** any doc is in a non-terminal state; interval disabled once all are
  `ready`/`failed`.

Components stay small and focused: `KbList`, `KbCreateForm`, `KbDetail`, `UploadDropzone`,
`DocumentRow`, `StatusPill`. Data access via a typed `api.ts` client + TanStack Query hooks.

---

## 7. Worker & compose wiring

- New `worker` service in `docker-compose.yml`: reuses the **api image**, command
  `uv run --no-dev arq app.worker.WorkerSettings`, `env_file: .env`, `depends_on:
  [postgres, redis, milvus]`, shares the `./storage` and (built-in) source. Same
  `DATABASE_URL`/`REDIS_URL`/`MILVUS_URI`/NVIDIA env as api.
- Bring **Milvus** into the live path: apply the Phase-1-noted fixes now —
  etcd `--advertise-client-urls=http://etcd:2379`, add named volumes `etcddata:/etcd` and a
  milvus data volume, and gate `milvus`/`worker`/`api` startup appropriately. `./storage` is a
  shared mounted volume so api (writes upload) and worker (reads bytes) see the same files.
- `arq` + `pymilvus` + the extractor/embedder deps added to `api/pyproject.toml`.

---

## 8. Testing

TDD per task. The four interfaces make the pipeline testable with no key and no network.

- **`IngestionService`** — unit tests with in-memory fake Extractor/Embedder/VectorStore:
  asserts status transitions (`extracting→embedding→ready`), chunk rows written, `milvus_pk`
  set, `chunks_done==chunks_total`; an Extractor/Embedder exception → `status=failed` with
  error set and no partial chunks; empty extraction → `failed`.
- **`Chunker`** — unit: boundary sizes, page-ref preservation, empty input, oversized single
  segment.
- **`NimEmbedder`** — contract test with mocked HTTP (response shape, dim, batching, retry on
  429/5xx); plus live verification with the real key.
- **`VectorStore`** — integration against the real Milvus container: `ensure_collection`
  idempotency, insert→count, partition isolation, delete-by-document_id.
- **Routes** — Phase-1 style (`dependency_overrides` + a fake job queue): ownership 404s,
  upload saves+enqueues exactly one job, size/mime guardrails, delete cascades.
- **Frontend** — component tests: KB-create renders+posts, upload posts multipart, status pills
  render from polled data, progress bar reflects counts.
- **Live verification pass** (Docker up + real key): upload a real PDF, watch it reach `ready`,
  confirm Milvus row count == chunk count, confirm a failed file isolates.

---

## 9. Deferred / carry-forward

- **SSE progress streaming** — deliberately deferred (user chose polling now). Revisit after
  Phase 3 builds the chat SSE infrastructure, then reuse it for live ingestion progress.
- Phase-1 carry-forwards remain open (OAuth single-origin hardening, auto-migrate entrypoint,
  email handling, SESSION_SECRET fail-fast, cross-platform npm lock). Not Phase-2 work; tracked
  in the progress ledger / project memory.

---

## 10. Definition of Done

- `docker compose up` brings up postgres, redis, milvus (healthy), api, **worker**, web.
- An authenticated user can create a KB, upload a pdf/docx/txt/md, and watch it reach `ready`
  via the polled status pill + progress bar; a malformed file reaches `failed` in isolation.
- Milvus contains one dense vector per chunk (count matches `chunks_total`); partitioned by KB.
- Delete removes Postgres rows, Milvus entries, and the stored file.
- `uv run pytest` (backend) and `npm test` (frontend) pass; live verification pass completed
  with a real NVIDIA key.
