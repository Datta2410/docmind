# YDG DocMind — Multimodal RAG Chatbot (Design Spec)

- **Date:** 2026-06-19
- **Status:** Approved design, ready for implementation planning
- **Working name:** YDG DocMind (rename anytime)
- **Goal:** A showcase system, built on NVIDIA NeMo Retriever, that ingests documents of all
  sorts — including the tables, charts, and scanned images inside them — and lets users chat
  with them through a polished web UI, with rich, verifiable citations.

---

## 1. Summary

DocMind is a multi-user web application. A user signs in with OAuth (Google / GitHub /
Twitter), creates persistent **knowledge bases**, uploads documents into them, and chats with
those documents. Retrieval is powered end-to-end by NVIDIA NeMo Retriever hosted NIM
microservices (multimodal extraction, embedding, reranking). Answer generation is performed by
a **swappable** LLM (NVIDIA NIM Llama / Claude / OpenAI). Every answer shows the exact source
chunks it used — including rendered tables and extracted charts — so the retrieval is visibly
trustworthy.

The flagship differentiator is **multimodal ingestion**: DocMind can answer questions whose
answers live inside a table or a chart buried in a PDF, and then show the user that exact table
or chart.

### Non-goals (POC scope)

- No self-hosting of NIM GPU containers by default (hosted endpoints only; see §10 mitigation).
- No team/org sharing of knowledge bases — KBs are owned by a single user.
- No billing, quotas, or usage metering.
- No fine-tuning of any model.

---

## 2. Decisions (locked during brainstorming)

| Area | Decision |
|---|---|
| Model hosting | **NVIDIA hosted NIMs** (build.nvidia.com / integrate.api.nvidia.com) — cheapest path to a POC, no GPU spend |
| Document scope | **Multimodal** — PDFs/Office docs with text, tables, charts, scanned images (nv-ingest) |
| Interface | **Web chat UI** |
| Generation LLM | **Configurable** — swappable router over NIM-Llama / Claude / OpenAI |
| Infra approach | **B — self-contained docker-compose** (FastAPI + React + Postgres + Milvus + Redis) |
| Auth | **Required OAuth** (Google / GitHub / Twitter) via Authlib; all features gated behind login |
| Persistence | **Named, persistent per-user knowledge bases** |
| Citations | **Rich** — source chunks with page numbers, rendered tables, and extracted charts |
| Stack | **FastAPI (async) + React + Vite + TypeScript** |

---

## 3. Architecture & components

Single repo, brought up with `docker compose up`.

| Service | Tech | Responsibility |
|---|---|---|
| `web` | React + Vite + TS, Tailwind, TanStack Query | Chat UI, OAuth login, KB management, upload, citation panel |
| `api` | FastAPI (async) | Auth/session, KB & doc CRUD, chat orchestration, SSE token streaming |
| `worker` | arq (Redis-backed) | Async ingestion jobs (extract → chunk → embed → index) |
| `postgres` | Postgres 16 | Users, knowledge bases, documents, chunk metadata, chat history |
| `milvus` | Milvus standalone | Vector store (dense + sparse hybrid), partitioned by knowledge base |
| `redis` | Redis | Job queue + ingestion progress/status |

**External (NVIDIA hosted NIMs, over HTTPS):**

- Embedding: `llama-3.2-nv-embedqa-1b-v2`
- Reranking: `llama-3.2-nv-rerankqa-1b-v2`
- Extraction (nv-ingest): page-elements, table-structure, graphic-elements/chart, OCR

The `worker` runs **nv-ingest in library mode** pointed at hosted NIM endpoints, so no GPU
containers run on our side.

**Generation** sits behind an `LLMRouter` interface with adapters for NIM-Llama, Claude, and
OpenAI, selected per knowledge base (`knowledge_bases.gen_model`) or per request.

### Key internal boundaries (independently testable, transport-agnostic)

- **`IngestionService`** — bytes in → indexed chunks out. Knows nothing about HTTP/React.
- **`RetrievalService`** — question + KB in → reranked, cited context out.
- **`LLMRouter`** — context + question in → streamed answer out; hides provider differences.

---

## 4. Data model

### Postgres (relational + human-facing content)

```
users           id, oauth_provider, oauth_subject, email, name, avatar_url, created_at
knowledge_bases id, owner_id→users, name, description, gen_model, created_at
documents       id, kb_id→knowledge_bases, filename, mime, size, status, page_count,
                error, uploaded_at        # status: queued|extracting|embedding|ready|failed
chunks          id, document_id→documents, kb_id, page_no, kind, text,
                table_html, image_uri, milvus_pk   # kind: text|table|chart|image
chat_sessions   id, kb_id, user_id, title, created_at
messages        id, session_id, role, content, citations(jsonb), created_at
```

`chunks` is the bridge between the two stores: rich renderable content (table HTML, chart image
path, page number) lives in Postgres for the citation panel; the **vector** for that same chunk
lives in Milvus, joined by `milvus_pk`.

Uploaded original files are written to a local `./storage` volume; the path is recorded on
`documents` so the citation panel can deep-link to the source page.

### Milvus (vectors)

One collection, **partitioned by `kb_id`**. Each entry:
`pk, kb_id, document_id, dense_vector, sparse_vector, text`.

- Partitioning by KB enforces multi-tenancy (a query only searches its own KB) and speeds search.
- `dense_vector` = embedding NIM output; `sparse_vector` = BM25-style term weights.
- Milvus natively fuses dense + sparse for **hybrid search**.

---

## 5. Ingestion pipeline (multimodal flagship)

On upload, `api` stores the file, creates a `documents` row (`status=queued`), and enqueues an
arq job. The `worker` runs:

```
1. EXTRACT   nv-ingest (library mode) → hosted NIM endpoints
             → per page: text blocks, tables (structured HTML),
               charts (extracted data + caption), OCR'd image text
2. CHUNK     semantic chunking of prose; tables & charts kept whole as their own
             chunks (kind=table|chart) so structure is never split mid-row
3. EMBED     batch chunks → llama-3.2-nv-embedqa → dense vectors
             + compute sparse vectors for hybrid search
4. INDEX     write vectors to Milvus (partition=kb_id);
             write chunk text/table_html/image_uri/page_no to Postgres
5. STATUS    update documents.status (extracting→embedding→ready);
             push progress to Redis → frontend live progress bar
```

- **Per-document failure isolation:** a doc that fails extraction goes `status=failed` with the
  error stored; it does not block sibling docs in the batch. Re-upload retries cleanly.
- **Payoff:** "what was Q3 margin?" can be answered from a chart or table inside a PDF, then the
  citation panel shows that exact table/chart.

---

## 6. Retrieval & generation

When a user sends a message in a KB chat, `api` runs `RetrievalService` then `LLMRouter`:

```
1. EMBED query → llama-3.2-nv-embedqa
2. HYBRID SEARCH Milvus (partition=kb_id): dense + sparse, fused → top-20 candidates
3. RERANK the 20 → llama-3.2-nv-rerankqa → keep top-5 by relevance
4. BUILD CONTEXT stitch the 5 chunks (text/table-HTML/chart-data) + source metadata
   into a grounded prompt with citation markers [1]..[5]
5. GENERATE via LLMRouter (NIM-Llama | Claude | OpenAI per KB config),
   streamed token-by-token over SSE
6. ATTACH the 5 source chunks as structured citations on the message
```

- **Retrieve-then-rerank** (wide net at 20 → precision pass to 5) is the pattern NeMo Retriever
  is built for and visibly lifts answer quality.
- The prompt instructs the model to **cite inline with `[n]` markers** and to **refuse to answer
  from outside the provided context** — "I don't find that in your documents" is a valid answer,
  not a hallucination.

---

## 7. Auth & frontend shell

**Auth:** Authlib in FastAPI runs the OAuth dance against Google / GitHub / Twitter apps. On
success, upsert the `users` row and issue a signed, HTTP-only session cookie (JWT inside). Every
`/api/*` route except OAuth callbacks requires a valid session. No passwords are ever stored.

**Frontend stack:** React + Vite + TypeScript, TanStack Query for server state, Tailwind for
styling, SSE for streaming tokens, and lightweight polling (or websocket) for ingestion progress.

---

## 8. Rich citations

Each assistant message carries a `citations` array (the 5 reranked chunks). Inline `[n]` markers
in the answer are clickable; clicking opens a **source panel** showing that chunk exactly as
extracted:

- prose snippet, **or** the **rendered table** (from `table_html`), **or** the **chart image/data**;
- plus *"Document X · page N"* with an **Open source** link that opens the original file at that page.

This panel is the literal proof that the multimodal pipeline works.

---

## 9. Error handling & resilience

- **Config-driven NIM endpoints** — every model URL is an env var (see §10).
- **Graceful degradation** — if the chart NIM is unavailable, charts fall back to OCR text rather
  than failing the whole document.
- **Rate-limit/retry with backoff** on all hosted NIM calls (hosted endpoints throttle).
- **Per-document failure isolation** with visible error states in the UI.
- **Grounded refusal** — generation refuses to answer outside retrieved context.

---

## 10. Hosted-NIM availability risk & mitigation

nv-ingest orchestrates several distinct extraction models (page-elements, table-structure,
chart/graphic-elements, OCR), each a separate NIM with its own endpoint. NVIDIA's hosted catalog
changes, and not every model is guaranteed to be available as a hosted endpoint at a given time.

**Mitigation:** every model endpoint is a config value (env var), e.g.:

```
NIM_PAGE_ELEMENTS_URL=https://integrate.api.nvidia.com/...
NIM_TABLE_STRUCTURE_URL=https://integrate.api.nvidia.com/...
NIM_CHART_URL=http://chart-nim:8000        # may point at a local container instead
NIM_OCR_URL=https://integrate.api.nvidia.com/...
```

If a single model becomes self-host-only, we add **just that one** container to
`docker-compose.yml` and repoint its env var — application code is unchanged. Worst case, that
model is skipped and the pipeline degrades gracefully (§9).

---

## 11. Configuration

`.env.example` documents every key:

- `NVIDIA_API_KEY`
- `NIM_*_URL` (embedding, rerank, and each extraction model)
- OAuth: `GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET`, `TWITTER_CLIENT_ID/SECRET`
- Generation providers: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (optional; NIM-Llama is default)
- `SESSION_SECRET`, `POSTGRES_*`, `MILVUS_*`, `REDIS_URL`

`docker compose up` is the only command needed to run the whole system.

---

## 12. Build phases (drives the implementation plan)

1. **Skeleton** — compose stack up; OAuth login; empty authenticated shell.
2. **Ingestion core** — upload → nv-ingest (text-only first) → embed → Milvus → `ready`.
3. **Chat core** — hybrid search → rerank → generation → streamed answers. *(MVP demoable here.)*
4. **Multimodal** — tables + charts extraction, kept as their own chunks.
5. **Rich citations** — source panel with rendered tables/charts + page links.
6. **Polish** — KB management, progress bars, model switcher, graceful degradation.

---

## 13. UX walkthrough (target experience)

A signed-out user sees only the YDG DocMind landing screen and three OAuth buttons. After signing
in, they land on a grid of knowledge-base cards (initially just **+ New knowledge base**). Creating
one opens a drop zone for files. Dropping a 40-page deck shows a live status pill
(`Extracting ▸ Embedding ▸ Ready`) with a progress bar, ending in
*"40 pages · 312 chunks · 8 tables · 5 charts."*

In chat, the user asks a question; the answer streams in with clickable `[n]` citation chips.
Clicking one slides in a source panel showing the exact table or chart the fact came from, with a
page reference and link to the original. A model dropdown (Llama / Claude / GPT) lets them switch
the generation model and re-ask. The user never thinks about Milvus, embeddings, or rerankers —
they just get cited, trustworthy answers.
