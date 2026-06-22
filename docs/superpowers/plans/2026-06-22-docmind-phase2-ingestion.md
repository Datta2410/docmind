# YDG DocMind — Phase 2: Ingestion Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authenticated user create a knowledge base, upload a document, and watch it move `queued → extracting → embedding → ready` as the backend extracts text (nv-ingest), chunks it, embeds it (NVIDIA NIM), and indexes dense vectors into Milvus.

**Architecture:** A new `app/ingest/` package defines four interfaces — `Extractor`, `Embedder`, `VectorStore`, and a `Chunker` — orchestrated by a transport-agnostic `IngestionService`. An arq worker runs ingestion jobs off Redis. FastAPI routes handle KB/document CRUD + upload; the React frontend adds routing, a KB list/create view, and a KB-detail upload view that polls document status.

**Tech Stack:** Phase-1 stack (FastAPI async, uv, SQLAlchemy 2.0 async, Alembic, React+Vite+TS+Tailwind+TanStack Query) plus: `arq` (Redis job queue), `pymilvus` (vector store), `nv-ingest-client`/`nv-ingest` (extraction), `python-multipart` (upload), `react-router-dom` (frontend routing).

## Global Constraints

- Python dependency manager is **uv**; never `pip`. Run via `uv run`. Backend root `api/app/`, tests `api/tests/`. Frontend root `web/`.
- All `/api/*` routes except `/api/health` and `/api/auth/*` require a valid session (Phase-1 `current_user` dependency). KB-scoped routes enforce `kb.owner_id == current_user.id`; mismatch → **404** (never leak existence).
- pytest is configured `asyncio_mode = "auto"` (`api/pyproject.toml`); async tests/fixtures need NO marker. The in-memory DB test fixture uses `sqlite+aiosqlite` and `Base.metadata.create_all` (see existing `api/tests/test_users_repo.py`).
- nv-ingest is the **sole** extractor — no fallback. Task 1 is a go/no-go spike; if it cannot extract text in the container, STOP and escalate to the user.
- Embedding dimension is config-driven (`settings.embed_dim`), never hardcoded in logic.
- Per-document failure isolation: any exception during ingestion sets `documents.status='failed'` with `error` set; it never blocks sibling documents or the queue.
- Product name in UI copy: **YDG DocMind**. Conventional Commit per task.
- `.env` is git-ignored; document every new key in `.env.example`.
- Phase-1 environment fact: the host has a native Postgres on `localhost:5432` that shadows the Docker port — run migrations **in-network** (`docker compose run --rm api uv run --no-dev alembic upgrade head`), not host-side.

---

## File Structure (Phase 2)

```
api/
├── pyproject.toml                      # +arq, pymilvus, nv-ingest, python-multipart
├── app/
│   ├── config.py                       # +embed_dim, nim/milvus/redis/upload settings
│   ├── models.py                       # +KnowledgeBase, Document, Chunk
│   ├── repos/
│   │   ├── knowledge_bases.py          # KB CRUD (ownership-scoped)
│   │   └── documents.py                # Document + Chunk persistence, status updates
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── types.py                    # TextSegment, Chunk dataclasses
│   │   ├── extractor.py                # Extractor Protocol
│   │   ├── nvingest_extractor.py       # NvIngestExtractor (sole impl)
│   │   ├── chunker.py                  # Chunker
│   │   ├── embedder.py                 # Embedder Protocol + StubEmbedder
│   │   ├── nim_embedder.py             # NimEmbedder (NVIDIA NIM)
│   │   ├── vector_store.py             # MilvusVectorStore
│   │   └── service.py                  # IngestionService
│   ├── storage.py                      # file path helpers (./storage/{kb}/{doc}/{name})
│   ├── queue.py                        # arq pool accessor + enqueue helper
│   ├── worker.py                       # arq WorkerSettings + ingest task
│   ├── routes/
│   │   ├── knowledge_bases.py          # /api/kbs*
│   │   └── documents.py                # /api/kbs/{id}/documents*, /api/documents/{id}
│   └── main.py                         # include new routers
│   └── migrations/versions/0002_*.py   # kb/documents/chunks tables
└── tests/
    ├── test_models_phase2.py
    ├── test_kb_repo.py
    ├── test_document_repo.py
    ├── test_chunker.py
    ├── test_embedder.py
    ├── test_nim_embedder.py
    ├── test_vector_store.py            # marked integration (real Milvus)
    ├── test_ingestion_service.py
    ├── test_kb_routes.py
    └── test_document_routes.py
web/
├── package.json                        # +react-router-dom
└── src/
    ├── main.tsx                        # wrap in BrowserRouter
    ├── App.tsx                         # Routes: / and /kb/:id (gated)
    ├── api.ts                          # +KB/document client fns
    ├── hooks/kbs.ts                    # TanStack Query hooks (incl. polling)
    └── components/
        ├── KbList.tsx
        ├── KbCreateForm.tsx
        ├── KbDetail.tsx
        ├── UploadDropzone.tsx
        ├── DocumentRow.tsx
        ├── StatusPill.tsx
        └── __tests__/{KbCreateForm,DocumentRow}.test.tsx
```

---

## Task 1: nv-ingest spike (GO/NO-GO GATE)

**Goal:** Prove nv-ingest installs in the API/worker image and extracts text from a real PDF, BEFORE any pipeline code depends on it. This is a gate, not a feature — its deliverable is a recorded verdict.

**Files:**
- Create: `api/spikes/nvingest_spike.py` (throwaway, committed for the record)
- Modify: `api/pyproject.toml` (add nv-ingest client dep)

**Interfaces:**
- Produces: a documented verdict (GO/NO-GO) + the exact nv-ingest client API used (function/class names, how to point it at hosted NIM endpoints, the shape of its returned text), which Task 4 consumes to write `NvIngestExtractor`.

- [ ] **Step 1: Add the nv-ingest client dependency**

Run:
```bash
cd api && uv add nv-ingest-client
```
Expected: resolves and locks. If resolution fails on Python 3.12, try `uv add "nv-ingest-api"` or the documented client package name from build.nvidia.com docs; record exactly which package and version resolved. If NO package resolves cleanly, STOP and escalate to the user with the resolver error (this is a NO-GO).

- [ ] **Step 2: Write the spike script**

Create `api/spikes/nvingest_spike.py`:
```python
"""Throwaway spike: prove nv-ingest extracts text from a PDF via hosted NIM.
Run inside the API container with NVIDIA_API_KEY set. Records the client API
shape that NvIngestExtractor (Task 4) will wrap. Not imported by app code.
"""
import os
import sys

def main(pdf_path: str) -> int:
    # The exact import path is what this spike discovers and records.
    # As of nv-ingest-client, the documented entrypoint is Ingestor.
    from nv_ingest_client.client import Ingestor  # noqa: discover real path

    api_key = os.environ["NVIDIA_API_KEY"]
    # Point at hosted NIM endpoints (no local GPU). The spike records the
    # exact kwargs that work against build.nvidia.com.
    result = (
        Ingestor()
        .files(pdf_path)
        .extract(extract_text=True, extract_tables=False,
                 extract_charts=False, extract_images=False)
        .ingest()
    )
    print("RESULT_TYPE:", type(result))
    print("RESULT_REPR:", repr(result)[:1000])
    # Record how to pull plain text + page numbers out of `result`.
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```
(If the real client API differs from `Ingestor().files().extract().ingest()`, adapt the spike to whatever the installed package actually exposes and record the working form — that recorded form is the task's main deliverable.)

- [ ] **Step 3: Build the image with nv-ingest and run the spike in-container**

Run (a sample PDF lives at `api/spikes/sample.pdf` — create one with any text PDF, e.g. `printf '%%PDF...'` is not enough; use a real PDF you drop in):
```bash
cd /Users/ydg/Documents/YDGTech/ydg-docmind
docker compose build api
docker compose run --rm -e NVIDIA_API_KEY=$NVIDIA_API_KEY \
  -v "$PWD/api/spikes:/app/spikes" api \
  uv run --no-dev python spikes/nvingest_spike.py spikes/sample.pdf
```
Expected: the script prints `RESULT_TYPE`/`RESULT_REPR` and visibly contains text extracted from the PDF. Capture the output.

- [ ] **Step 4: Record the verdict**

Append a `## nv-ingest spike verdict` section to the task report containing: GO or NO-GO; the resolved package name+version; the exact working client-call form; how text + page numbers are read from the result object; image size delta (`docker images ydg-docmind_api`). 

**If NO-GO** (won't install, won't run in-container, or can't reach hosted NIM): STOP. Report BLOCKED to the controller, who escalates to the user — Phase 2 does not proceed on a substitute extractor per the spec.

- [ ] **Step 5: Commit**

```bash
git add api/pyproject.toml api/uv.lock api/spikes/
git commit -m "chore: nv-ingest install+extract spike (go/no-go gate)"
```

---

## Task 2: Phase-2 models + migration 0002

**Files:**
- Modify: `api/app/models.py`
- Create: `api/migrations/versions/0002_kb_documents_chunks.py`
- Test: `api/tests/test_models_phase2.py`

**Interfaces:**
- Consumes: `app.db.Base`, Phase-1 `User`.
- Produces:
  - `KnowledgeBase(id, owner_id, name, description, gen_model, created_at)`
  - `Document(id, kb_id, filename, mime, size, status, page_count, error, chunks_total, chunks_done, uploaded_at)`
  - `Chunk(id, document_id, kb_id, page_no, kind, text, table_html, image_uri, milvus_pk)`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_models_phase2.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app.models import User, KnowledgeBase, Document, Chunk


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_kb_document_chunk_roundtrip(db):
    u = User(oauth_provider="google", oauth_subject="s", email="a@x.com", name="A")
    db.add(u); await db.commit(); await db.refresh(u)

    kb = KnowledgeBase(owner_id=u.id, name="Board Pack")
    db.add(kb); await db.commit(); await db.refresh(kb)
    assert kb.gen_model == "nim-llama"          # default

    doc = Document(kb_id=kb.id, filename="q3.pdf", mime="application/pdf", size=1234)
    db.add(doc); await db.commit(); await db.refresh(doc)
    assert doc.status == "queued"               # default
    assert doc.chunks_total == 0 and doc.chunks_done == 0

    ch = Chunk(document_id=doc.id, kb_id=kb.id, page_no=1, text="hello")
    db.add(ch); await db.commit(); await db.refresh(ch)
    assert ch.kind == "text"                    # default
    assert ch.table_html is None and ch.milvus_pk is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_models_phase2.py -v`
Expected: FAIL — `ImportError: cannot import name 'KnowledgeBase'`.

- [ ] **Step 3: Write minimal implementation**

Append to `api/app/models.py`:
```python
from sqlalchemy import ForeignKey, Integer, Text, BigInteger
from sqlalchemy.orm import relationship


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    gen_model: Mapped[str] = mapped_column(String(64), default="nim-llama",
                                           server_default="nim-llama")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued",
                                        server_default="queued")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunks_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="text", server_default="text")
    text: Mapped[str] = mapped_column(Text)
    table_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    milvus_pk: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_models_phase2.py -v`
Expected: PASS.

- [ ] **Step 5: Hand-write the migration**

Create `api/migrations/versions/0002_kb_documents_chunks.py` (hand-written, mirroring the model columns; `down_revision = "0001"`):
```python
"""kb, documents, chunks

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2048), nullable=True),
        sa.Column("gen_model", sa.String(64), server_default="nim-llama", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunks_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), server_default="text", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("table_html", sa.Text(), nullable=True),
        sa.Column("image_uri", sa.String(1024), nullable=True),
        sa.Column("milvus_pk", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
```

- [ ] **Step 6: Validate the migration loads (no DB needed)**

Run: `cd api && uv run alembic history`
Expected: lists `0001 -> 0002, kb, documents, chunks` with no import error.

- [ ] **Step 7: Commit**

```bash
git add api/app/models.py api/migrations/versions/0002_kb_documents_chunks.py api/tests/test_models_phase2.py
git commit -m "feat: phase-2 models and migration (kb, documents, chunks)"
```

---

## Task 3: Config + ingest types + storage helpers

**Files:**
- Modify: `api/app/config.py`
- Create: `api/app/ingest/__init__.py`, `api/app/ingest/types.py`, `api/app/storage.py`
- Test: `api/tests/test_storage.py`

**Interfaces:**
- Consumes: `app.config.Settings`.
- Produces:
  - `Settings` fields: `nvidia_api_key: str`, `nim_embed_url: str`, `embed_model: str` (default `"nvidia/llama-3.2-nv-embedqa-1b-v2"`), `embed_dim: int` (default `2048`), `embed_batch_size: int` (default `64`), `milvus_uri: str`, `redis_url: str`, `storage_dir: str` (default `"./storage"`), `max_upload_mb: int` (default `25`), `allowed_mimes: str` (csv).
  - `app.ingest.types.TextSegment(text: str, page_no: int)` and `Chunk(text: str, page_no: int)` (frozen dataclasses).
  - `app.storage.document_path(storage_dir, kb_id, document_id, filename) -> str`; `app.storage.save_bytes(path, data) -> None`; `app.storage.read_bytes(path) -> bytes`; `app.storage.delete_document_dir(storage_dir, kb_id, document_id) -> None`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_storage.py`:
```python
from app.storage import document_path, save_bytes, read_bytes, delete_document_dir


def test_path_and_roundtrip(tmp_path):
    root = str(tmp_path)
    p = document_path(root, kb_id=3, document_id=7, filename="q3.pdf")
    assert p.endswith("/3/7/q3.pdf")
    save_bytes(p, b"hello")
    assert read_bytes(p) == b"hello"
    delete_document_dir(root, 3, 7)
    import os
    assert not os.path.exists(os.path.dirname(p))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.storage'`.

- [ ] **Step 3: Write minimal implementation**

Add to `api/app/config.py` `Settings`:
```python
    nvidia_api_key: str = ""
    nim_embed_url: str = "https://integrate.api.nvidia.com/v1"
    embed_model: str = "nvidia/llama-3.2-nv-embedqa-1b-v2"
    embed_dim: int = 2048
    embed_batch_size: int = 64
    milvus_uri: str = "http://localhost:19530"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage"
    max_upload_mb: int = 25
    allowed_mimes: str = "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
```

Create `api/app/ingest/__init__.py` (empty).

Create `api/app/ingest/types.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TextSegment:
    text: str
    page_no: int


@dataclass(frozen=True)
class Chunk:
    text: str
    page_no: int
```

Create `api/app/storage.py`:
```python
import os
import shutil


def document_path(storage_dir: str, kb_id: int, document_id: int, filename: str) -> str:
    return os.path.join(storage_dir, str(kb_id), str(document_id), filename)


def save_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def delete_document_dir(storage_dir: str, kb_id: int, document_id: int) -> None:
    d = os.path.join(storage_dir, str(kb_id), str(document_id))
    shutil.rmtree(d, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/config.py api/app/ingest/__init__.py api/app/ingest/types.py api/app/storage.py api/tests/test_storage.py
git commit -m "feat: phase-2 config, ingest types, storage helpers"
```

---

## Task 4: Extractor interface + NvIngestExtractor

**Files:**
- Create: `api/app/ingest/extractor.py`, `api/app/ingest/nvingest_extractor.py`
- Test: `api/tests/test_extractor.py`

**Interfaces:**
- Consumes: Task 1's recorded nv-ingest client API; `app.ingest.types.TextSegment`; `app.config.get_settings`.
- Produces:
  - `app.ingest.extractor.Extractor` (Protocol): `async def extract(self, data: bytes, mime: str) -> list[TextSegment]`.
  - `app.ingest.nvingest_extractor.NvIngestExtractor` implementing it via nv-ingest text mode. Empty result → returns `[]` (the service treats empty as a failure, not the extractor).

- [ ] **Step 1: Write the failing test** (tests the Protocol shape + that a fake satisfies it; the real nv-ingest call is exercised in the live pass, not unit tests)

Create `api/tests/test_extractor.py`:
```python
from app.ingest.extractor import Extractor
from app.ingest.types import TextSegment


class FakeExtractor:
    async def extract(self, data: bytes, mime: str) -> list[TextSegment]:
        return [TextSegment(text="page one", page_no=1)]


async def test_fake_satisfies_protocol_and_returns_segments():
    ex: Extractor = FakeExtractor()
    segs = await ex.extract(b"%PDF", "application/pdf")
    assert segs == [TextSegment(text="page one", page_no=1)]
    assert isinstance(ex, Extractor)        # runtime_checkable Protocol
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingest.extractor'`.

- [ ] **Step 3: Write the Protocol**

Create `api/app/ingest/extractor.py`:
```python
from typing import Protocol, runtime_checkable
from app.ingest.types import TextSegment


@runtime_checkable
class Extractor(Protocol):
    async def extract(self, data: bytes, mime: str) -> list[TextSegment]:
        ...
```

- [ ] **Step 4: Write NvIngestExtractor using the spike's recorded API**

Create `api/app/ingest/nvingest_extractor.py`. Use the EXACT client call form recorded in Task 1's verdict. The template below assumes the `Ingestor` form; if Task 1 recorded a different shape, use that instead. nv-ingest is sync, so run it in a thread to stay async-friendly:
```python
import asyncio
import os
import tempfile
from app.config import get_settings
from app.ingest.types import TextSegment


class NvIngestExtractor:
    """Extracts plain text (+ page numbers) via nv-ingest in text mode,
    pointed at hosted NVIDIA NIM endpoints. Sole Extractor implementation."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def extract(self, data: bytes, mime: str) -> list[TextSegment]:
        return await asyncio.to_thread(self._extract_sync, data, mime)

    def _extract_sync(self, data: bytes, mime: str) -> list[TextSegment]:
        from nv_ingest_client.client import Ingestor   # path per Task 1 verdict
        os.environ.setdefault("NVIDIA_API_KEY", self._settings.nvidia_api_key)
        with tempfile.NamedTemporaryFile(suffix=_suffix_for(mime)) as tmp:
            tmp.write(data); tmp.flush()
            result = (
                Ingestor()
                .files(tmp.name)
                .extract(extract_text=True, extract_tables=False,
                         extract_charts=False, extract_images=False)
                .ingest()
            )
        return _to_segments(result)


def _suffix_for(mime: str) -> str:
    return {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/plain": ".txt",
        "text/markdown": ".md",
    }.get(mime, ".bin")


def _to_segments(result) -> list[TextSegment]:
    """Map nv-ingest output to ordered TextSegments. Exact field access per
    Task 1 verdict; this reads text elements with their page numbers."""
    segments: list[TextSegment] = []
    for doc in result:                         # result iterates per-document
        for element in doc:                    # elements per document
            text = (element.get("content") or "").strip()
            if not text:
                continue
            page = int(element.get("metadata", {}).get("page_number", 1))
            segments.append(TextSegment(text=text, page_no=page))
    return segments
```
(Adjust `_to_segments` field access to match the real result structure Task 1 recorded. Keep the public `extract` signature identical regardless.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_extractor.py -v`
Expected: PASS. (`NvIngestExtractor`'s real call is covered by the live verification pass, Task 12.)

- [ ] **Step 6: Commit**

```bash
git add api/app/ingest/extractor.py api/app/ingest/nvingest_extractor.py api/tests/test_extractor.py
git commit -m "feat: Extractor protocol and NvIngestExtractor (text mode)"
```

---

## Task 5: Chunker

**Files:**
- Create: `api/app/ingest/chunker.py`
- Test: `api/tests/test_chunker.py`

**Interfaces:**
- Consumes: `app.ingest.types.TextSegment`, `Chunk`.
- Produces: `app.ingest.chunker.Chunker(max_chars=1200, overlap=150)` with `chunk(self, segments: list[TextSegment]) -> list[Chunk]`. Splits each segment into ≤`max_chars` pieces with `overlap` carryover, preserving `page_no`. Empty/whitespace input → `[]`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_chunker.py`:
```python
from app.ingest.chunker import Chunker
from app.ingest.types import TextSegment


def test_short_segment_one_chunk_keeps_page():
    out = Chunker(max_chars=100, overlap=10).chunk([TextSegment("hello world", 3)])
    assert len(out) == 1
    assert out[0].text == "hello world" and out[0].page_no == 3


def test_long_segment_splits_with_overlap_and_page():
    text = "abcdefghij" * 30          # 300 chars
    out = Chunker(max_chars=100, overlap=20).chunk([TextSegment(text, 5)])
    assert len(out) >= 3
    assert all(len(c.text) <= 100 for c in out)
    assert all(c.page_no == 5 for c in out)
    # overlap: end of chunk 0 reappears at start of chunk 1
    assert out[0].text[-20:] == out[1].text[:20]


def test_empty_and_whitespace_yield_nothing():
    assert Chunker().chunk([]) == []
    assert Chunker().chunk([TextSegment("   ", 1)]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingest.chunker'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/app/ingest/chunker.py`:
```python
from app.ingest.types import TextSegment, Chunk


class Chunker:
    def __init__(self, max_chars: int = 1200, overlap: int = 150) -> None:
        if overlap >= max_chars:
            raise ValueError("overlap must be < max_chars")
        self.max_chars = max_chars
        self.overlap = overlap

    def chunk(self, segments: list[TextSegment]) -> list[Chunk]:
        out: list[Chunk] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if len(text) <= self.max_chars:
                out.append(Chunk(text=text, page_no=seg.page_no))
                continue
            start = 0
            step = self.max_chars - self.overlap
            while start < len(text):
                piece = text[start:start + self.max_chars]
                if piece.strip():
                    out.append(Chunk(text=piece, page_no=seg.page_no))
                start += step
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_chunker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/ingest/chunker.py api/tests/test_chunker.py
git commit -m "feat: Chunker with overlap and page preservation"
```

---

## Task 6: Embedder interface + StubEmbedder + NimEmbedder

**Files:**
- Create: `api/app/ingest/embedder.py`, `api/app/ingest/nim_embedder.py`
- Test: `api/tests/test_embedder.py`, `api/tests/test_nim_embedder.py`

**Interfaces:**
- Consumes: `app.config.get_settings`.
- Produces:
  - `app.ingest.embedder.Embedder` (Protocol): `async def embed(self, texts: list[str]) -> list[list[float]]`.
  - `app.ingest.embedder.StubEmbedder(dim: int)` — deterministic vectors (hash-seeded), no network.
  - `app.ingest.nim_embedder.NimEmbedder` — POSTs to `{nim_embed_url}/embeddings` with model `embed_model`, batches by `embed_batch_size`, retries 429/5xx; returns one vector per input text, order preserved.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_embedder.py`:
```python
from app.ingest.embedder import Embedder, StubEmbedder


async def test_stub_is_deterministic_and_right_dim():
    e: Embedder = StubEmbedder(dim=8)
    a = await e.embed(["hello", "world"])
    b = await e.embed(["hello", "world"])
    assert len(a) == 2 and len(a[0]) == 8
    assert a == b                      # deterministic
    assert a[0] != a[1]                # different inputs differ
    assert isinstance(e, Embedder)
```

Create `api/tests/test_nim_embedder.py`:
```python
import httpx
import pytest
from app.ingest.nim_embedder import NimEmbedder


async def test_nim_embedder_batches_and_preserves_order(monkeypatch):
    calls = []

    async def fake_post(self, url, **kwargs):
        payload = kwargs["json"]
        calls.append(payload["input"])
        data = [{"embedding": [float(len(t))] * 4} for t in payload["input"]]
        return httpx.Response(200, json={"data": data})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    emb = NimEmbedder(api_key="k", base_url="http://nim", model="m",
                      dim=4, batch_size=2)
    out = await emb.embed(["a", "bb", "ccc"])
    assert len(out) == 3 and all(len(v) == 4 for v in out)
    assert out[1] == [2.0, 2.0, 2.0, 2.0]      # "bb" -> len 2
    assert calls == [["a", "bb"], ["ccc"]]     # batched by 2, order kept
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_embedder.py tests/test_nim_embedder.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write minimal implementations**

Create `api/app/ingest/embedder.py`:
```python
import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class StubEmbedder:
    """Deterministic, network-free embeddings for tests/dev."""
    def __init__(self, dim: int) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            vec = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(self.dim)]
            out.append(vec)
        return out
```

Create `api/app/ingest/nim_embedder.py`:
```python
import asyncio
import httpx


class NimEmbedder:
    def __init__(self, api_key: str, base_url: str, model: str,
                 dim: int, batch_size: int = 64) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                data = await self._post_with_retry(client, batch)
                out.extend(item["embedding"] for item in data)
        return out

    async def _post_with_retry(self, client, batch, attempts=4):
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": batch, "input_type": "passage"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(attempts):
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()["data"]
        resp.raise_for_status()
        return resp.json()["data"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_embedder.py tests/test_nim_embedder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/ingest/embedder.py api/app/ingest/nim_embedder.py api/tests/test_embedder.py api/tests/test_nim_embedder.py
git commit -m "feat: Embedder protocol, StubEmbedder, NimEmbedder with batching+retry"
```

---

## Task 7: VectorStore (Milvus)

**Files:**
- Create: `api/app/ingest/vector_store.py`
- Test: `api/tests/test_vector_store.py` (marked integration)

**Interfaces:**
- Consumes: `app.config.get_settings`, `pymilvus`.
- Produces: `app.ingest.vector_store.MilvusVectorStore(uri, dim, collection="docmind_chunks")` with:
  - `ensure_collection() -> None` (idempotent: collection + HNSW index + load)
  - `insert(kb_id: int, document_id: int, vectors: list[list[float]], texts: list[str]) -> list[int]` (returns milvus PKs, ordered; uses partition `kb_{kb_id}`)
  - `delete_document(document_id: int) -> None`
  - `count(kb_id: int) -> int`

- [ ] **Step 1: Write the integration test** (real Milvus; skipped unless `MILVUS_URI` set)

Create `api/tests/test_vector_store.py`:
```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MILVUS_URI"),
    reason="requires a running Milvus (set MILVUS_URI)",
)


async def test_ensure_insert_count_delete():
    from app.ingest.vector_store import MilvusVectorStore
    store = MilvusVectorStore(uri=os.environ["MILVUS_URI"], dim=8,
                              collection="docmind_test")
    store.ensure_collection()
    store.ensure_collection()                       # idempotent
    pks = store.insert(kb_id=1, document_id=42,
                       vectors=[[0.1] * 8, [0.2] * 8], texts=["a", "b"])
    assert len(pks) == 2
    assert store.count(kb_id=1) >= 2
    store.delete_document(document_id=42)
```

- [ ] **Step 2: Run test to verify it fails (or skips without Milvus)**

Run: `cd api && uv run pytest tests/test_vector_store.py -v`
Expected: FAIL on import (`No module named 'app.ingest.vector_store'`) when `MILVUS_URI` unset it would skip — so run with a dummy to force collection: it should FAIL at import first. Acceptable expected: collection error or import error.

- [ ] **Step 3: Write minimal implementation**

Create `api/app/ingest/vector_store.py`:
```python
from pymilvus import (
    MilvusClient, DataType,
)


class MilvusVectorStore:
    def __init__(self, uri: str, dim: int, collection: str = "docmind_chunks") -> None:
        self.client = MilvusClient(uri=uri)
        self.dim = dim
        self.collection = collection

    def ensure_collection(self) -> None:
        if self.client.has_collection(self.collection):
            self.client.load_collection(self.collection)
            return
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("kb_id", DataType.INT64)
        schema.add_field("document_id", DataType.INT64)
        schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="dense_vector", index_type="HNSW",
                               metric_type="IP", params={"M": 16, "efConstruction": 200})
        self.client.create_collection(self.collection, schema=schema,
                                      index_params=index_params)
        self.client.load_collection(self.collection)

    def insert(self, kb_id: int, document_id: int,
               vectors: list[list[float]], texts: list[str]) -> list[int]:
        rows = [
            {"kb_id": kb_id, "document_id": document_id,
             "dense_vector": v, "text": t[:8192]}
            for v, t in zip(vectors, texts)
        ]
        res = self.client.insert(self.collection, rows)
        return list(res["ids"])

    def delete_document(self, document_id: int) -> None:
        self.client.delete(self.collection, filter=f"document_id == {document_id}")

    def count(self, kb_id: int) -> int:
        res = self.client.query(self.collection, filter=f"kb_id == {kb_id}",
                                output_fields=["count(*)"])
        return int(res[0]["count(*)"]) if res else 0
```
(Partitioning: `MilvusClient` auto-manages; kb isolation is enforced by the `kb_id` filter at query time in Phase 3. The spec's "partition by kb_id" is satisfied logically via the `kb_id` field + filter; a physical partition is a Phase-3 optimization. Note this in the report.)

- [ ] **Step 4: Run test against real Milvus**

Bring Milvus up (`docker compose up -d etcd minio milvus`), then:
Run: `cd api && MILVUS_URI=http://localhost:19530 uv run pytest tests/test_vector_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/ingest/vector_store.py api/tests/test_vector_store.py
git commit -m "feat: MilvusVectorStore (ensure/insert/count/delete)"
```

---

## Task 8: Repos (knowledge_bases + documents)

**Files:**
- Create: `api/app/repos/knowledge_bases.py`, `api/app/repos/documents.py`
- Test: `api/tests/test_kb_repo.py`, `api/tests/test_document_repo.py`

**Interfaces:**
- Consumes: models from Task 2.
- Produces:
  - `repos.knowledge_bases`: `create_kb(db, *, owner_id, name, description=None) -> KnowledgeBase`; `list_kbs(db, owner_id) -> list[KnowledgeBase]`; `get_kb(db, kb_id, owner_id) -> KnowledgeBase | None` (ownership-scoped).
  - `repos.documents`: `create_document(db, *, kb_id, filename, mime, size) -> Document`; `list_documents(db, kb_id) -> list[Document]`; `get_document(db, document_id) -> Document | None`; `set_status(db, document_id, status, *, error=None, page_count=None) -> None`; `set_chunk_counts(db, document_id, *, total=None, done=None) -> None`; `add_chunks(db, chunks: list[Chunk]) -> list[Chunk]` (ORM Chunk rows); `delete_document(db, document_id) -> None` (cascades chunk rows).

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_kb_repo.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app.models import User
from app.repos.knowledge_bases import create_kb, list_kbs, get_kb


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _user(db, sub):
    u = User(oauth_provider="google", oauth_subject=sub, email=f"{sub}@x.com", name=sub)
    db.add(u); await db.commit(); await db.refresh(u); return u


async def test_create_list_get_scoped_by_owner(db):
    a = await _user(db, "a"); b = await _user(db, "b")
    kb = await create_kb(db, owner_id=a.id, name="A's KB")
    assert kb.id is not None
    assert [k.id for k in await list_kbs(db, a.id)] == [kb.id]
    assert await list_kbs(db, b.id) == []
    assert await get_kb(db, kb.id, a.id) is not None
    assert await get_kb(db, kb.id, b.id) is None        # ownership isolation
```

Create `api/tests/test_document_repo.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app.models import User, KnowledgeBase, Chunk
from app.repos.documents import (
    create_document, list_documents, get_document, set_status,
    set_chunk_counts, add_chunks, delete_document,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _kb(db):
    u = User(oauth_provider="g", oauth_subject="s", email="e@x.com", name="n")
    db.add(u); await db.commit(); await db.refresh(u)
    kb = KnowledgeBase(owner_id=u.id, name="kb")
    db.add(kb); await db.commit(); await db.refresh(kb); return kb


async def test_document_lifecycle(db):
    kb = await _kb(db)
    doc = await create_document(db, kb_id=kb.id, filename="f.pdf",
                                mime="application/pdf", size=10)
    assert doc.status == "queued"
    await set_status(db, doc.id, "extracting")
    await set_chunk_counts(db, doc.id, total=2, done=0)
    rows = await add_chunks(db, [Chunk(document_id=doc.id, kb_id=kb.id,
                                       page_no=1, text="a")])
    assert rows[0].id is not None
    await set_status(db, doc.id, "ready", page_count=1)
    got = await get_document(db, doc.id)
    assert got.status == "ready" and got.page_count == 1
    assert [d.id for d in await list_documents(db, kb.id)] == [doc.id]
    await delete_document(db, doc.id)
    assert await get_document(db, doc.id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_kb_repo.py tests/test_document_repo.py -v`
Expected: FAIL — repo modules not found.

- [ ] **Step 3: Write minimal implementations**

Create `api/app/repos/knowledge_bases.py`:
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import KnowledgeBase


async def create_kb(db: AsyncSession, *, owner_id: int, name: str,
                    description: str | None = None) -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner_id, name=name, description=description)
    db.add(kb); await db.commit(); await db.refresh(kb)
    return kb


async def list_kbs(db: AsyncSession, owner_id: int) -> list[KnowledgeBase]:
    res = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.owner_id == owner_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(res.scalars().all())


async def get_kb(db: AsyncSession, kb_id: int, owner_id: int) -> KnowledgeBase | None:
    res = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id,
                                    KnowledgeBase.owner_id == owner_id)
    )
    return res.scalar_one_or_none()
```

Create `api/app/repos/documents.py`:
```python
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Document, Chunk


async def create_document(db: AsyncSession, *, kb_id: int, filename: str,
                          mime: str, size: int) -> Document:
    doc = Document(kb_id=kb_id, filename=filename, mime=mime, size=size)
    db.add(doc); await db.commit(); await db.refresh(doc)
    return doc


async def list_documents(db: AsyncSession, kb_id: int) -> list[Document]:
    res = await db.execute(
        select(Document).where(Document.kb_id == kb_id)
        .order_by(Document.uploaded_at.desc())
    )
    return list(res.scalars().all())


async def get_document(db: AsyncSession, document_id: int) -> Document | None:
    return await db.get(Document, document_id)


async def set_status(db: AsyncSession, document_id: int, status: str, *,
                     error: str | None = None, page_count: int | None = None) -> None:
    doc = await db.get(Document, document_id)
    doc.status = status
    if error is not None:
        doc.error = error[:2000]
    if page_count is not None:
        doc.page_count = page_count
    await db.commit()


async def set_chunk_counts(db: AsyncSession, document_id: int, *,
                           total: int | None = None, done: int | None = None) -> None:
    doc = await db.get(Document, document_id)
    if total is not None:
        doc.chunks_total = total
    if done is not None:
        doc.chunks_done = done
    await db.commit()


async def add_chunks(db: AsyncSession, chunks: list[Chunk]) -> list[Chunk]:
    db.add_all(chunks)
    await db.commit()
    for c in chunks:
        await db.refresh(c)
    return chunks


async def delete_document(db: AsyncSession, document_id: int) -> None:
    await db.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
    await db.execute(sa_delete(Document).where(Document.id == document_id))
    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_kb_repo.py tests/test_document_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/repos/knowledge_bases.py api/app/repos/documents.py api/tests/test_kb_repo.py api/tests/test_document_repo.py
git commit -m "feat: knowledge_bases and documents repositories"
```

---

## Task 9: IngestionService (the orchestrator)

**Files:**
- Create: `api/app/ingest/service.py`
- Test: `api/tests/test_ingestion_service.py`

**Interfaces:**
- Consumes: repos (Task 8), `Extractor`/`Chunker`/`Embedder`/`VectorStore`, `app.storage`, `app.ingest.types`, models.
- Produces: `app.ingest.service.IngestionService(db, extractor, chunker, embedder, vector_store, storage_dir)` with `async def ingest(self, document_id: int) -> None`. Drives status transitions, writes chunk rows + vectors, sets `milvus_pk`, increments `chunks_done`. Any exception → `status=failed` + `error`; empty extraction → `failed` ("no extractable text").

- [ ] **Step 1: Write the failing test** (fakes for all four collaborators; real sqlite db)

Create `api/tests/test_ingestion_service.py`:
```python
import os
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app.models import User, KnowledgeBase
from app.repos.documents import create_document, get_document
from app.ingest.types import TextSegment
from app.ingest.chunker import Chunker
from app.ingest.embedder import StubEmbedder
from app.ingest.service import IngestionService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


class FakeExtractor:
    def __init__(self, segments): self.segments = segments
    async def extract(self, data, mime): return self.segments


class FakeStore:
    def __init__(self): self.rows = []
    def ensure_collection(self): pass
    def insert(self, kb_id, document_id, vectors, texts):
        base = len(self.rows)
        self.rows.extend(texts)
        return [base + i for i in range(len(texts))]   # fake PKs


async def _doc_with_file(db, tmp_path):
    u = User(oauth_provider="g", oauth_subject="s", email="e@x.com", name="n")
    db.add(u); await db.commit(); await db.refresh(u)
    kb = KnowledgeBase(owner_id=u.id, name="kb")
    db.add(kb); await db.commit(); await db.refresh(kb)
    doc = await create_document(db, kb_id=kb.id, filename="f.txt",
                                mime="text/plain", size=5)
    from app.storage import document_path, save_bytes
    save_bytes(document_path(str(tmp_path), kb.id, doc.id, "f.txt"), b"hello")
    return kb, doc


async def test_happy_path_sets_ready_and_pks(db, tmp_path):
    kb, doc = await _doc_with_file(db, tmp_path)
    svc = IngestionService(
        db=db,
        extractor=FakeExtractor([TextSegment("hello world", 1)]),
        chunker=Chunker(max_chars=5, overlap=0),
        embedder=StubEmbedder(dim=8),
        vector_store=FakeStore(),
        storage_dir=str(tmp_path),
    )
    await svc.ingest(doc.id)
    got = await get_document(db, doc.id)
    assert got.status == "ready"
    assert got.chunks_total == got.chunks_done > 0
    assert got.page_count == 1


async def test_empty_extraction_marks_failed(db, tmp_path):
    kb, doc = await _doc_with_file(db, tmp_path)
    svc = IngestionService(db=db, extractor=FakeExtractor([]),
                           chunker=Chunker(), embedder=StubEmbedder(dim=8),
                           vector_store=FakeStore(), storage_dir=str(tmp_path))
    await svc.ingest(doc.id)
    got = await get_document(db, doc.id)
    assert got.status == "failed" and "no extractable text" in got.error.lower()


async def test_embedder_error_marks_failed(db, tmp_path):
    kb, doc = await _doc_with_file(db, tmp_path)
    class BoomEmbedder:
        async def embed(self, texts): raise RuntimeError("nim down")
    svc = IngestionService(db=db, extractor=FakeExtractor([TextSegment("hi", 1)]),
                           chunker=Chunker(), embedder=BoomEmbedder(),
                           vector_store=FakeStore(), storage_dir=str(tmp_path))
    await svc.ingest(doc.id)
    got = await get_document(db, doc.id)
    assert got.status == "failed" and "nim down" in got.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_ingestion_service.py -v`
Expected: FAIL — `No module named 'app.ingest.service'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/app/ingest/service.py`:
```python
from app.models import Chunk as ChunkRow
from app.repos.documents import (
    get_document, set_status, set_chunk_counts, add_chunks,
)
from app.storage import document_path, read_bytes


class IngestionService:
    def __init__(self, *, db, extractor, chunker, embedder, vector_store,
                 storage_dir: str) -> None:
        self.db = db
        self.extractor = extractor
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.storage_dir = storage_dir

    async def ingest(self, document_id: int) -> None:
        doc = await get_document(self.db, document_id)
        if doc is None:
            return
        try:
            path = document_path(self.storage_dir, doc.kb_id, doc.id, doc.filename)
            data = read_bytes(path)

            await set_status(self.db, doc.id, "extracting")
            segments = await self.extractor.extract(data, doc.mime)
            if not segments:
                await set_status(self.db, doc.id, "failed",
                                 error="no extractable text in document")
                return
            page_count = max(s.page_no for s in segments)

            await set_status(self.db, doc.id, "embedding", page_count=page_count)
            chunks = self.chunker.chunk(segments)
            if not chunks:
                await set_status(self.db, doc.id, "failed",
                                 error="no extractable text after chunking")
                return
            await set_chunk_counts(self.db, doc.id, total=len(chunks), done=0)

            self.vector_store.ensure_collection()
            vectors = await self.embedder.embed([c.text for c in chunks])

            rows = [ChunkRow(document_id=doc.id, kb_id=doc.kb_id,
                             page_no=c.page_no, text=c.text) for c in chunks]
            rows = await add_chunks(self.db, rows)
            pks = self.vector_store.insert(doc.kb_id, doc.id, vectors,
                                           [c.text for c in chunks])
            for row, pk in zip(rows, pks):
                row.milvus_pk = pk
            await set_chunk_counts(self.db, doc.id, done=len(chunks))
            await self.db.commit()

            await set_status(self.db, doc.id, "ready")
        except Exception as exc:                # per-document isolation
            await self.db.rollback()
            await set_status(self.db, doc.id, "failed", error=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_ingestion_service.py -v`
Expected: PASS (happy path + both failure isolations).

- [ ] **Step 5: Commit**

```bash
git add api/app/ingest/service.py api/tests/test_ingestion_service.py
git commit -m "feat: IngestionService orchestration with per-document failure isolation"
```

---

## Task 10: arq worker + queue + compose wiring

**Files:**
- Create: `api/app/queue.py`, `api/app/worker.py`
- Modify: `api/pyproject.toml` (arq), `docker-compose.yml` (worker service + Milvus fixes), `.env.example`
- Test: `api/tests/test_queue.py`

**Interfaces:**
- Consumes: `IngestionService` + concrete impls, `app.config`, `app.db.SessionLocal`.
- Produces:
  - `app.queue.enqueue_ingest(document_id: int) -> None` (pushes an arq job); `app.queue.get_pool()`.
  - `app.worker.WorkerSettings` (arq) with an `ingest` task that builds an `IngestionService` (NvIngestExtractor + Chunker + NimEmbedder + MilvusVectorStore) and runs it.

- [ ] **Step 1: Add arq + write the failing test**

Run: `cd api && uv add arq`

Create `api/tests/test_queue.py`:
```python
from app import queue


async def test_enqueue_uses_pool(monkeypatch):
    jobs = []

    class FakePool:
        async def enqueue_job(self, name, *args):
            jobs.append((name, args))

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr(queue, "get_pool", fake_get_pool)
    await queue.enqueue_ingest(99)
    assert jobs == [("ingest", (99,))]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_queue.py -v`
Expected: FAIL — `No module named 'app.queue'`.

- [ ] **Step 3: Write queue + worker**

Create `api/app/queue.py`:
```python
from arq import create_pool
from arq.connections import RedisSettings
from app.config import get_settings

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue_ingest(document_id: int) -> None:
    pool = await get_pool()
    await pool.enqueue_job("ingest", document_id)
```

Create `api/app/worker.py`:
```python
from arq.connections import RedisSettings
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.service import IngestionService
from app.ingest.nvingest_extractor import NvIngestExtractor
from app.ingest.chunker import Chunker
from app.ingest.nim_embedder import NimEmbedder
from app.ingest.vector_store import MilvusVectorStore


async def ingest(ctx, document_id: int) -> None:
    s = get_settings()
    async with SessionLocal() as db:
        service = IngestionService(
            db=db,
            extractor=NvIngestExtractor(),
            chunker=Chunker(),
            embedder=NimEmbedder(api_key=s.nvidia_api_key, base_url=s.nim_embed_url,
                                 model=s.embed_model, dim=s.embed_dim,
                                 batch_size=s.embed_batch_size),
            vector_store=MilvusVectorStore(uri=s.milvus_uri, dim=s.embed_dim),
            storage_dir=s.storage_dir,
        )
        await service.ingest(document_id)


class WorkerSettings:
    functions = [ingest]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Wire compose + env, applying the Milvus fixes**

In `docker-compose.yml`: (a) change etcd command to `--advertise-client-urls=http://etcd:2379`; (b) add `etcddata:/etcd` volume to etcd and declare `etcddata:` + a `milvusdata:/var/lib/milvus` volume; (c) add the `worker` service and a shared `storage` mount:
```yaml
  worker:
    build: ./api
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://docmind:docmind@postgres:5432/docmind
    command: ["uv", "run", "--no-dev", "arq", "app.worker.WorkerSettings"]
    volumes: ["storage:/app/storage"]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      milvus: { condition: service_started }
```
Add `volumes: ["storage:/app/storage"]` to the `api` service too, and declare `storage:` under top-level `volumes:`. Add `STORAGE_DIR=/app/storage` and the NIM/embedding keys to `.env.example`.

Validate offline: `docker compose config -q` → exit 0.

- [ ] **Step 6: Commit**

```bash
git add api/app/queue.py api/app/worker.py api/pyproject.toml api/uv.lock docker-compose.yml .env.example api/tests/test_queue.py
git commit -m "feat: arq worker + queue, compose worker service and milvus fixes"
```

---

## Task 11: KB + document routes

**Files:**
- Create: `api/app/routes/knowledge_bases.py`, `api/app/routes/documents.py`
- Modify: `api/app/main.py`, `api/pyproject.toml` (`python-multipart`)
- Test: `api/tests/test_kb_routes.py`, `api/tests/test_document_routes.py`

**Interfaces:**
- Consumes: `current_user`, repos, `app.storage`, `app.queue.enqueue_ingest`, `get_settings`.
- Produces routes from spec §5. Upload validates mime allowlist + size (413), saves bytes, creates `documents` row, enqueues exactly one job, returns the row. All KB-scoped routes 404 on non-owned KB.

- [ ] **Step 1: Add multipart + write failing tests**

Run: `cd api && uv add python-multipart`

Create `api/tests/test_kb_routes.py`:
```python
from app.models import User
from app.session import current_user
from app.db import get_db
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_create_and_list_kb(app, client, session_factory):
    async def _db():
        async with session_factory() as s:
            yield s
    user = User(id=1, oauth_provider="g", oauth_subject="s", email="e@x.com", name="n")
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = lambda: user
    try:
        r = await client.post("/api/kbs", json={"name": "My KB"})
        assert r.status_code == 201
        assert r.json()["name"] == "My KB"
        r2 = await client.get("/api/kbs")
        assert r2.status_code == 200 and len(r2.json()) == 1
    finally:
        app.dependency_overrides.clear()
```

Create `api/tests/test_document_routes.py`:
```python
import io
from app.models import User, KnowledgeBase
from app.session import current_user
from app.db import get_db, Base
from app import queue
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_upload_enqueues_one_job(app, client, session_factory, tmp_path, monkeypatch):
    jobs = []
    async def fake_enqueue(doc_id): jobs.append(doc_id)
    monkeypatch.setattr(queue, "enqueue_ingest", fake_enqueue)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    factory = session_factory
    async with factory() as s:
        u = User(oauth_provider="g", oauth_subject="s", email="e@x.com", name="n")
        s.add(u); await s.commit(); await s.refresh(u)
        kb = KnowledgeBase(owner_id=u.id, name="kb")
        s.add(kb); await s.commit(); await s.refresh(kb)
        kb_id, user_id = kb.id, u.id

    async def _db():
        async with factory() as s:
            yield s
    user = User(id=user_id, oauth_provider="g", oauth_subject="s",
                email="e@x.com", name="n")
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = lambda: user
    try:
        files = {"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
        r = await client.post(f"/api/kbs/{kb_id}/documents", files=files)
        assert r.status_code == 201
        assert r.json()["status"] == "queued"
        assert len(jobs) == 1
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_kb_routes.py tests/test_document_routes.py -v`
Expected: FAIL — routes 404 (not wired).

- [ ] **Step 3: Write the routes + wire them**

Create `api/app/routes/knowledge_bases.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.session import current_user
from app.models import User
from app.repos.knowledge_bases import create_kb, list_kbs, get_kb

router = APIRouter()


class KbCreate(BaseModel):
    name: str
    description: str | None = None


def _kb_json(kb):
    return {"id": kb.id, "name": kb.name, "description": kb.description,
            "gen_model": kb.gen_model}


@router.post("/api/kbs", status_code=201)
async def create(body: KbCreate, user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    kb = await create_kb(db, owner_id=user.id, name=body.name,
                         description=body.description)
    return _kb_json(kb)


@router.get("/api/kbs")
async def list_all(user: User = Depends(current_user),
                   db: AsyncSession = Depends(get_db)):
    return [_kb_json(k) for k in await list_kbs(db, user.id)]


@router.get("/api/kbs/{kb_id}")
async def get_one(kb_id: int, user: User = Depends(current_user),
                  db: AsyncSession = Depends(get_db)):
    kb = await get_kb(db, kb_id, user.id)
    if kb is None:
        raise HTTPException(status_code=404, detail="not found")
    return _kb_json(kb)
```

Create `api/app/routes/documents.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.session import current_user
from app.models import User
from app.config import get_settings
from app.repos.knowledge_bases import get_kb
from app.repos.documents import (
    create_document, list_documents, get_document, delete_document,
)
from app.storage import document_path, save_bytes, delete_document_dir
from app import queue
from app.ingest.vector_store import MilvusVectorStore

router = APIRouter()


def _doc_json(d):
    return {"id": d.id, "filename": d.filename, "mime": d.mime, "size": d.size,
            "status": d.status, "page_count": d.page_count, "error": d.error,
            "chunks_total": d.chunks_total, "chunks_done": d.chunks_done}


@router.post("/api/kbs/{kb_id}/documents", status_code=201)
async def upload(kb_id: int, file: UploadFile = File(...),
                 user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    s = get_settings()
    kb = await get_kb(db, kb_id, user.id)
    if kb is None:
        raise HTTPException(status_code=404, detail="not found")
    allowed = set(s.allowed_mimes.split(","))
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="unsupported file type")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large")
    doc = await create_document(db, kb_id=kb_id, filename=file.filename,
                                mime=file.content_type, size=len(data))
    save_bytes(document_path(s.storage_dir, kb_id, doc.id, file.filename), data)
    await queue.enqueue_ingest(doc.id)
    return _doc_json(doc)


@router.get("/api/kbs/{kb_id}/documents")
async def list_docs(kb_id: int, user: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    kb = await get_kb(db, kb_id, user.id)
    if kb is None:
        raise HTTPException(status_code=404, detail="not found")
    return [_doc_json(d) for d in await list_documents(db, kb_id)]


@router.delete("/api/documents/{document_id}", status_code=204)
async def delete(document_id: int, user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)):
    s = get_settings()
    doc = await get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    kb = await get_kb(db, doc.kb_id, user.id)
    if kb is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        MilvusVectorStore(uri=s.milvus_uri, dim=s.embed_dim).delete_document(document_id)
    except Exception:
        pass                                   # Milvus cleanup best-effort
    delete_document_dir(s.storage_dir, doc.kb_id, document_id)
    await delete_document(db, document_id)
```

Modify `api/app/main.py` `create_app()` to include both routers:
```python
from app.routes import health, me, knowledge_bases, documents
# ...
    app.include_router(knowledge_bases.router)
    app.include_router(documents.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_kb_routes.py tests/test_document_routes.py -v`
Expected: PASS. Then full suite: `uv run pytest -v` (skips the Milvus integration test without `MILVUS_URI`).

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/knowledge_bases.py api/app/routes/documents.py api/app/main.py api/pyproject.toml api/uv.lock api/tests/test_kb_routes.py api/tests/test_document_routes.py
git commit -m "feat: KB and document routes (create/list/get/upload/delete)"
```

---

## Task 12: Frontend — KB list/create, upload, status polling

**Files:**
- Modify: `web/package.json` (react-router-dom), `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api.ts`, `web/src/components/AppShell.tsx`
- Create: `web/src/hooks/kbs.ts`, `web/src/components/{KbList,KbCreateForm,KbDetail,UploadDropzone,DocumentRow,StatusPill}.tsx`, `web/src/components/__tests__/{KbCreateForm,DocumentRow}.test.tsx`
- (Live verification pass at the end)

**Interfaces:**
- Consumes: Phase-2 API routes. Produces routed views gated by Phase-1 auth: Home (`/`) lists/creates KBs; KB detail (`/kb/:id`) uploads + polls document status.

- [ ] **Step 1: Add router + write the failing component tests**

Run: `cd web && npm install react-router-dom`

Create `web/src/components/__tests__/KbCreateForm.test.tsx`:
```tsx
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { KbCreateForm } from "../KbCreateForm"

describe("KbCreateForm", () => {
  it("submits the typed name", () => {
    const onCreate = vi.fn()
    render(<KbCreateForm onCreate={onCreate} />)
    fireEvent.change(screen.getByPlaceholderText(/knowledge base name/i),
      { target: { value: "Board Pack" } })
    fireEvent.click(screen.getByRole("button", { name: /create/i }))
    expect(onCreate).toHaveBeenCalledWith("Board Pack")
  })
})
```

Create `web/src/components/__tests__/DocumentRow.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { DocumentRow } from "../DocumentRow"

describe("DocumentRow", () => {
  it("shows filename, status pill, and progress for embedding docs", () => {
    render(<DocumentRow doc={{ id: 1, filename: "q3.pdf", status: "embedding",
      chunks_total: 10, chunks_done: 4, page_count: 12, error: null }} />)
    expect(screen.getByText("q3.pdf")).toBeInTheDocument()
    expect(screen.getByText(/embedding/i)).toBeInTheDocument()
    expect(screen.getByText("4 / 10")).toBeInTheDocument()
  })

  it("shows error text for failed docs", () => {
    render(<DocumentRow doc={{ id: 2, filename: "bad.pdf", status: "failed",
      chunks_total: 0, chunks_done: 0, page_count: null, error: "no extractable text" }} />)
    expect(screen.getByText(/no extractable text/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — components not found.

- [ ] **Step 3: Implement the components, hooks, API client, and routing**

Create `web/src/api.ts` additions (append):
```ts
export type Kb = { id: number; name: string; description: string | null; gen_model: string }
export type Doc = {
  id: number; filename: string; status: string
  chunks_total: number; chunks_done: number; page_count: number | null; error: string | null
}

export async function listKbs(): Promise<Kb[]> {
  const r = await fetch("/api/kbs"); if (!r.ok) throw new Error("kbs"); return r.json()
}
export async function createKb(name: string): Promise<Kb> {
  const r = await fetch("/api/kbs", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) })
  if (!r.ok) throw new Error("create"); return r.json()
}
export async function listDocs(kbId: number): Promise<Doc[]> {
  const r = await fetch(`/api/kbs/${kbId}/documents`); if (!r.ok) throw new Error("docs"); return r.json()
}
export async function uploadDoc(kbId: number, file: File): Promise<Doc> {
  const fd = new FormData(); fd.append("file", file)
  const r = await fetch(`/api/kbs/${kbId}/documents`, { method: "POST", body: fd })
  if (!r.ok) throw new Error("upload"); return r.json()
}
```

Create `web/src/hooks/kbs.ts`:
```ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listKbs, createKb, listDocs, uploadDoc, type Doc } from "../api"

export function useKbs() {
  return useQuery({ queryKey: ["kbs"], queryFn: listKbs })
}
export function useCreateKb() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: createKb,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["kbs"] }) })
}
const TERMINAL = new Set(["ready", "failed"])
export function useDocs(kbId: number) {
  return useQuery({
    queryKey: ["docs", kbId],
    queryFn: () => listDocs(kbId),
    refetchInterval: (q) => {
      const docs = (q.state.data as Doc[] | undefined) ?? []
      const anyActive = docs.some((d) => !TERMINAL.has(d.status))
      return anyActive ? 2000 : false
    },
  })
}
export function useUpload(kbId: number) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (file: File) => uploadDoc(kbId, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["docs", kbId] }) })
}
```

Create `web/src/components/StatusPill.tsx`:
```tsx
const COLORS: Record<string, string> = {
  queued: "bg-slate-200 text-slate-700",
  extracting: "bg-amber-100 text-amber-800",
  embedding: "bg-blue-100 text-blue-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
}
export function StatusPill({ status }: { status: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs ${COLORS[status] ?? ""}`}>{status}</span>
}
```

Create `web/src/components/DocumentRow.tsx`:
```tsx
import type { Doc } from "../api"
import { StatusPill } from "./StatusPill"

export function DocumentRow({ doc }: { doc: Doc }) {
  return (
    <div className="flex items-center justify-between border-b py-2">
      <div className="flex flex-col">
        <span className="font-medium">{doc.filename}</span>
        {doc.status === "failed" && doc.error && (
          <span className="text-xs text-red-600">{doc.error}</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        {doc.status === "embedding" && (
          <span className="text-xs text-slate-500">{doc.chunks_done} / {doc.chunks_total}</span>
        )}
        <StatusPill status={doc.status} />
      </div>
    </div>
  )
}
```

Create `web/src/components/KbCreateForm.tsx`:
```tsx
import { useState } from "react"

export function KbCreateForm({ onCreate }: { onCreate: (name: string) => void }) {
  const [name, setName] = useState("")
  return (
    <form className="flex gap-2"
      onSubmit={(e) => { e.preventDefault(); if (name.trim()) onCreate(name.trim()) }}>
      <input value={name} onChange={(e) => setName(e.target.value)}
        placeholder="Knowledge base name"
        className="rounded border px-3 py-1.5" />
      <button type="submit" className="rounded bg-slate-900 px-3 py-1.5 text-white">Create</button>
    </form>
  )
}
```

Create `web/src/components/UploadDropzone.tsx`:
```tsx
import { useRef } from "react"

export function UploadDropzone({ onFile }: { onFile: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onFile(f) }}
      onClick={() => input.current?.click()}
      className="cursor-pointer rounded-xl border-2 border-dashed p-10 text-center text-slate-400">
      Drop a PDF, Word, or text file here, or click to choose
      <input ref={input} type="file" className="hidden"
        accept=".pdf,.docx,.txt,.md"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
    </div>
  )
}
```

Create `web/src/components/KbList.tsx`:
```tsx
import { Link } from "react-router-dom"
import { useKbs, useCreateKb } from "../hooks/kbs"
import { KbCreateForm } from "./KbCreateForm"

export function KbList() {
  const { data: kbs = [] } = useKbs()
  const create = useCreateKb()
  return (
    <div className="mx-auto max-w-3xl p-8">
      <h2 className="mb-4 text-xl font-semibold">Your knowledge bases</h2>
      <div className="mb-6"><KbCreateForm onCreate={(name) => create.mutate(name)} /></div>
      <div className="grid grid-cols-2 gap-4">
        {kbs.map((kb) => (
          <Link key={kb.id} to={`/kb/${kb.id}`}
            className="rounded-xl border p-4 hover:bg-slate-50">{kb.name}</Link>
        ))}
      </div>
    </div>
  )
}
```

Create `web/src/components/KbDetail.tsx`:
```tsx
import { useParams } from "react-router-dom"
import { useDocs, useUpload } from "../hooks/kbs"
import { UploadDropzone } from "./UploadDropzone"
import { DocumentRow } from "./DocumentRow"

export function KbDetail() {
  const { id } = useParams()
  const kbId = Number(id)
  const { data: docs = [] } = useDocs(kbId)
  const upload = useUpload(kbId)
  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="mb-6"><UploadDropzone onFile={(f) => upload.mutate(f)} /></div>
      <div>{docs.map((d) => <DocumentRow key={d.id} doc={d} />)}</div>
    </div>
  )
}
```

Modify `web/src/main.tsx` to wrap in `BrowserRouter`:
```tsx
import { BrowserRouter } from "react-router-dom"
// ...
  <QueryClientProvider client={qc}>
    <BrowserRouter><App /></BrowserRouter>
  </QueryClientProvider>
```

Modify `web/src/App.tsx` so the authenticated shell renders routes:
```tsx
import { Routes, Route } from "react-router-dom"
import { useMe } from "./auth"
import { LoginScreen } from "./components/LoginScreen"
import { AppShell } from "./components/AppShell"
import { KbList } from "./components/KbList"
import { KbDetail } from "./components/KbDetail"

export default function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return <div className="p-8 text-slate-400">Loading…</div>
  if (!me) return <LoginScreen />
  return (
    <AppShell user={me}>
      <Routes>
        <Route path="/" element={<KbList />} />
        <Route path="/kb/:id" element={<KbDetail />} />
      </Routes>
    </AppShell>
  )
}
```

Modify `web/src/components/AppShell.tsx` to render `children` in place of the static placeholder:
```tsx
// change the signature to accept children and render them in <main>:
export function AppShell({ user, children }: { user: User; children?: React.ReactNode }) {
  // ...header unchanged...
  // replace the placeholder <main> body with:
  //   <main className="p-0">{children}</main>
}
```
(Keep the existing header/avatar/sign-out markup; only swap the `<main>` placeholder for `{children}` and add `children` to the prop type with a `React` import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: PASS (KbCreateForm + DocumentRow). Then `npm run build` → typecheck+build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat: KB list/create, upload dropzone, document status polling"
```

- [ ] **Step 6: Live verification pass (Docker up + real NVIDIA key)**

Bring up the full stack and verify ingestion end-to-end with the real embedding NIM:
```bash
cd /Users/ydg/Documents/YDGTech/ydg-docmind
# set NVIDIA_API_KEY + embed_dim in .env (embed_dim must match the model's output)
docker compose up -d --build
docker compose run --rm api uv run --no-dev alembic upgrade head   # in-network (host pg shadows :5432)
docker compose ps           # postgres healthy; redis, milvus, api, worker, web up
```
Then in the browser (http://localhost:5173, signed in): create a KB, upload a real PDF, watch it move `queued → extracting → embedding → ready`. Confirm with:
```bash
docker compose exec -T postgres psql -U docmind -d docmind -c \
  "select status, chunks_total, chunks_done, page_count from documents order by id desc limit 1;"
docker compose logs worker --tail=30
```
Expected: document `ready`, `chunks_done == chunks_total > 0`; Milvus row count for the KB equals `chunks_total`. Upload a malformed/empty file → reaches `failed` in isolation without affecting the good one. Record results in the report. (If `embed_dim` mismatched the model, fix it in `.env`, recreate the Milvus collection, and re-ingest.)

---

## Phase 2 Done — Definition of Done

- `docker compose up` brings up postgres, redis, milvus (healthy), api, **worker**, web.
- Authenticated user creates a KB, uploads pdf/docx/txt/md, watches it reach `ready` via the polled status pill + progress bar; a malformed file reaches `failed` in isolation.
- Milvus holds one dense vector per chunk (count matches `chunks_total`), with `kb_id`/`document_id` fields.
- Delete removes Postgres rows, Milvus entries, and the stored file.
- `uv run pytest` (backend) and `npm test` (frontend) pass; live verification pass completed with a real NVIDIA key.

## Carry-forward to later phases
- Sparse vectors + hybrid index (Phase 3 retrieval).
- nv-ingest multimodal mode (tables/charts) behind the same `Extractor` (Phase 4).
- SSE progress streaming (deferred; reuse Phase-3 chat SSE infra).
- Physical Milvus partition-by-kb (Phase-3 optimization; logical kb_id filter for now).
- Phase-1 carry-forwards still open (OAuth single-origin, auto-migrate entrypoint, email handling, SESSION_SECRET fail-fast, cross-platform npm lock).
