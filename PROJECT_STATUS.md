# YDG DocMind — Project Status / Resume Here

_Last updated: 2026-06-22_

A capability-showcase **multimodal RAG chatbot** on NVIDIA NeMo Retriever.
Repo: GitHub **Datta2410/docmind** (public). Built via the superpowers
brainstorm → writing-plans → subagent-driven-development flow.

> **Resume in one line:** Phase 1 is done, merged, and live-verified. Phase 2
> (ingestion) is mid-flight on branch `phase2-ingestion`; the next action is a
> **plan/spec revision** (see "Next action" below) before continuing execution.

---

## How to run what exists today (Phase 1)

```bash
docker compose up -d --build
# host has a native Postgres on :5432 that SHADOWS the container — run migrations in-network:
docker compose run --rm api uv run --no-dev alembic upgrade head
# open http://localhost:5173  (login screen; OAuth needs real app creds to complete)
docker compose down            # stop (keeps data volumes); add -v to wipe data
```
Tests: backend `cd api && uv run pytest`; frontend `cd web && npm test`.

Secrets live in git-ignored `.env` (copy from `.env.example`). `NVIDIA_API_KEY`
is already set locally. `.env` is NOT committed.

---

## Roadmap (6 phases)

1. **Skeleton** — ✅ DONE, merged to `main`, live-verified.
2. **Ingestion core** — 🔶 IN PROGRESS on `phase2-ingestion` (see below).
3. Chat core (MVP: hybrid search → rerank → generation, SSE streaming).
4. Multimodal (nv-ingest tables/charts).
5. Rich citations.
6. Polish.

---

## Phase 1 — DONE (on `main`)

FastAPI (async, uv) + React/Vite/TS/Tailwind + Postgres + Milvus + Redis via
docker-compose. OAuth-gated (Google/GitHub/Twitter, Authlib), signed-cookie
sessions, `User` model + migration `0001`, routes `/api/health`, `/api/me`,
`/api/auth/*`. React login screen + auth gate + shell.

**Live-verified (2026-06-20):** stack comes up; migration applies to real
Postgres; `/api/health`→200, `/api/me`→401, Google login→302 (well-formed
redirect; a *completed* login still needs registered OAuth app creds); nginx
`/api` proxy + SPA fallback work; backend 9/9 + frontend 1/1 tests pass.

---

## Phase 2 — IN PROGRESS (branch `phase2-ingestion`)

**Goal:** create KB → upload doc → extract text → chunk → embed (hosted NIM) →
index dense vectors in Milvus → live (polled) status `queued→extracting→
embedding→ready`. Retrieval/chat is Phase 3.

**Artifacts on the branch:**
- Spec: `docs/superpowers/specs/2026-06-22-docmind-phase2-ingestion-design.md`
- Plan: `docs/superpowers/plans/2026-06-22-docmind-phase2-ingestion.md` (12 tasks)
- Progress ledger: `.superpowers/sdd/progress.md`
- Task 1 spike committed: `7299283` (branch HEAD). `main` is at `f5ddacb`.

**Task 1 (nv-ingest spike) — DONE, verdict GO, but it changed the architecture:**
- nv-ingest has **no hosted endpoint**. Its normal client (`Ingestor().ingest()`)
  needs the nv-ingest **microservice running**. (Separate from the embedding
  NIM, which IS hosted and real.)
- The only in-container path that worked is `pdfium_extractor` via an
  **internal** module `nv_ingest_api.internal.extract.pdf.engines.pdfium` —
  under the hood it's **local PDFium (CPU), no NIM**. Image ballooned to **~1 GB**
  with 8 undeclared transitive deps. Packages: `nv-ingest-client==26.3.0` +
  `nv-ingest-api==26.3.0`. Result shape: `list[[ContentTypeEnum, metadata, uuid]]`;
  text at `metadata["content"]`, page at `metadata["content_metadata"]["page_number"]`.

**Hard constraint discovered:** dev machine is **Apple Silicon M1 Pro, 16 GB,
arm64, no NVIDIA GPU.** The nv-ingest server is an amd64/CUDA stack → can't run
its GPU NIMs locally; only amd64-under-emulation. So running the real nv-ingest
server locally is impractical on this hardware.

### ▶ Next action (the decision to resume on)
User chose: **lightweight extractor now, real nv-ingest server at Phase 4.**
Concretely, when resuming:
1. **Revise the Phase 2 spec + plan**: replace `NvIngestExtractor` with a small
   CPU `PlainExtractor` (pypdf/pdfplumber for PDF, python-docx for docx, plain
   text for txt/md) behind the SAME `Extractor` interface; drop the ~1 GB
   nv-ingest dependency from the worker image; keep everything else (chunker,
   embedder=hosted NIM, Milvus dense-only, arq worker, routes, frontend polling).
2. Move the real **nv-ingest server** to Phase 4, to run on GPU hardware
   (cloud box) where multimodal table/chart extraction via hosted NIM lands.
3. Resume subagent-driven execution from **Task 2** (models + migration `0002`).
   The Task 1 spike commit stays as a record; nv-ingest deps it added to
   `api/pyproject.toml` should be removed during the revision.

**Phase-2 decisions still locked:** embedding = real hosted NIM
`llama-3.2-nv-embedqa-1b-v2` (`embed_dim=2048`) behind an `Embedder` interface
with a `StubEmbedder` for tests; Milvus **dense vectors only** now (hybrid in
Phase 3); progress via **polling** (SSE deferred).

---

## Standing carry-forwards (tracked, not yet done)

- **Phase-1 hardening:** OAuth single external origin behind nginx +
  `https_only`/SameSite (current redirect_uri hits :8000 directly; works on
  localhost only because cookies ignore port); api entrypoint that runs
  `alembic upgrade head`; GitHub `/user/emails` + Twitter email (email column
  NOT NULL, currently `""`); fail-fast on default `SESSION_SECRET`; produce a
  complete cross-platform npm lock and restore `npm ci`.
- **Infra:** etcd advertise-url + persistent volumes; milvus health-gated
  `depends_on`.
- **Env gotcha:** native host Postgres on `:5432` shadows the container — always
  migrate in-network (`docker compose run --rm api ... alembic upgrade head`).

---

## Conventions

- uv only (`uv run`), never pip. Backend `api/app/`, tests `api/tests/`,
  frontend `web/`. pytest `asyncio_mode="auto"`. Conventional Commits.
- Detailed per-task history in `.superpowers/sdd/progress.md`.
