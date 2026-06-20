# YDG DocMind

Multimodal RAG chatbot on NVIDIA NeMo Retriever. Upload documents (text, tables,
charts), chat with them, and see cited sources.

## Run (Phase 1: login + shell)

1. `cp .env.example .env` and set `SESSION_SECRET` and your OAuth app credentials.
   Register OAuth apps with callback `http://localhost:8000/api/auth/<provider>/callback`.
2. `docker compose up -d --build`
3. First run only — apply DB migrations:
   `cd api && DATABASE_URL=postgresql+asyncpg://docmind:docmind@localhost:5432/docmind uv run alembic upgrade head`
4. Open http://localhost:5173 and sign in.

## Tests
- Backend: `cd api && uv run pytest -v`
- Frontend: `cd web && npm test`
