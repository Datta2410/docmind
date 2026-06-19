# YDG DocMind — Phase 1: Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the full self-contained stack (`docker compose up`) with OAuth login (Google/GitHub/Twitter) gating an empty authenticated React shell.

**Architecture:** A FastAPI async backend handles OAuth via Authlib and persists users in Postgres through SQLAlchemy 2.0 async + Alembic. Sessions are signed cookies via Starlette `SessionMiddleware`. A React + Vite + TypeScript frontend shows a sign-in screen, gates all features behind `/api/me`, and renders an empty knowledge-base shell once authenticated. Postgres, Redis, and Milvus run as compose services now so later phases plug in without infra changes.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Authlib, SQLAlchemy 2.0 (async, asyncpg), Alembic, Starlette SessionMiddleware, pytest + pytest-asyncio, uv (Python deps); React 18 + Vite + TypeScript, Tailwind, TanStack Query, Vitest (frontend); Docker Compose (postgres:16, redis:7, milvusdb/milvus standalone).

## Global Constraints

- Python dependency manager is **uv**; never call `pip` directly. Run app code with `uv run`.
- Backend package root is `api/app/`; tests in `api/tests/`. Frontend root is `web/`.
- All `/api/*` routes except `/api/health` and `/api/auth/*` MUST require a valid session.
- No passwords are ever stored. Auth is OAuth-only (Google, GitHub, Twitter).
- Every secret/config value is read from environment; `.env` is git-ignored and `.env.example` documents every key.
- The whole system must come up with a single `docker compose up` (plus first-run `alembic upgrade head`).
- Product/working name in user-facing copy: **YDG DocMind**.
- Commit after every task with a `feat:`/`chore:`/`test:` Conventional Commit message.

---

## File Structure (Phase 1)

```
ydg-docmind/
├── docker-compose.yml              # postgres, redis, milvus, api, web
├── .env.example                    # every config key, documented
├── .gitignore                      # (exists) add .env, __pycache__, node_modules
├── README.md                       # how to run
├── api/
│   ├── pyproject.toml              # uv project, deps
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── migrations/                 # alembic env + versions
│   │   ├── env.py
│   │   └── versions/0001_users.py
│   └── app/
│       ├── __init__.py
│       ├── config.py               # Settings from env
│       ├── db.py                   # async engine + session factory
│       ├── models.py               # SQLAlchemy User model
│       ├── session.py              # current-user helpers / auth dependency
│       ├── repos/users.py          # upsert_user, get_user
│       ├── auth.py                 # Authlib OAuth registry + login/callback routes
│       ├── routes/
│       │   ├── health.py           # GET /api/health
│       │   └── me.py               # GET /api/me, POST /api/auth/logout
│       └── main.py                 # FastAPI app, middleware, router wiring
│   └── tests/
│       ├── conftest.py             # async test client + test DB
│       ├── test_health.py
│       ├── test_users_repo.py
│       ├── test_session.py
│       ├── test_auth_flow.py
│       └── test_me.py
└── web/
    ├── package.json
    ├── vite.config.ts              # dev proxy /api → api:8000
    ├── tailwind.config.js
    ├── index.html
    └── src/
        ├── main.tsx
        ├── api.ts                  # fetch helpers
        ├── auth.tsx                # useMe() hook + AuthGate
        ├── App.tsx
        ├── components/LoginScreen.tsx
        ├── components/AppShell.tsx
        └── components/__tests__/LoginScreen.test.tsx
```

---

## Task 1: Backend project scaffold + health endpoint

**Files:**
- Create: `api/pyproject.toml`, `api/app/__init__.py`, `api/app/config.py`, `api/app/routes/health.py`, `api/app/main.py`
- Test: `api/tests/conftest.py`, `api/tests/test_health.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `app.main.create_app() -> FastAPI`; `GET /api/health` → `{"status": "ok"}`. `app.config.Settings` (pydantic-settings) with fields used by later tasks: `database_url: str`, `session_secret: str`, `frontend_url: str`, plus OAuth fields added in Task 5.

- [ ] **Step 1: Initialize the uv project and add dependencies**

Run:
```bash
cd api
uv init --name docmind-api --python 3.12 --no-readme
uv add fastapi "uvicorn[standard]" "pydantic-settings>=2" "sqlalchemy[asyncio]>=2" asyncpg alembic "authlib>=1.3" itsdangerous httpx
uv add --dev pytest pytest-asyncio
```
Expected: `uv` creates `.venv` and writes deps into `pyproject.toml`. Delete any generated `hello.py`/`main.py` sample: `rm -f main.py hello.py`.

- [ ] **Step 2: Write the failing test**

Create `api/tests/conftest.py`:
```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import create_app

@pytest.fixture
def app():
    return create_app()

@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

Create `api/tests/test_health.py`:
```python
async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Add to `api/pyproject.toml` (so pytest finds `app` and runs async tests):
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
```
(`asyncio_mode = "auto"` means async test functions and `@pytest_asyncio.fixture` fixtures run without any per-test marker.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 4: Write minimal implementation**

Create `api/app/__init__.py` (empty file).

Create `api/app/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://docmind:docmind@localhost:5432/docmind"
    session_secret: str = "dev-insecure-change-me"
    frontend_url: str = "http://localhost:5173"

def get_settings() -> Settings:
    return Settings()
```

Create `api/app/routes/health.py`:
```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/health")
async def health():
    return {"status": "ok"}
```

Create `api/app/routes/__init__.py` (empty file).

Create `api/app/main.py`:
```python
from fastapi import FastAPI
from app.routes import health

def create_app() -> FastAPI:
    app = FastAPI(title="YDG DocMind API")
    app.include_router(health.router)
    return app

app = create_app()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/
git commit -m "feat: backend scaffold with health endpoint"
```

---

## Task 2: Database engine, User model, and migration

**Files:**
- Create: `api/app/db.py`, `api/app/models.py`, `api/app/repos/__init__.py`, `api/app/repos/users.py`, `api/alembic.ini`, `api/migrations/env.py`, `api/migrations/versions/0001_users.py`
- Test: `api/tests/test_users_repo.py`

**Interfaces:**
- Consumes: `app.config.get_settings`.
- Produces:
  - `app.db.engine`, `app.db.SessionLocal` (async sessionmaker), `app.db.get_db()` (FastAPI dependency yielding `AsyncSession`), `app.db.Base`.
  - `app.models.User` with columns `id: int`, `oauth_provider: str`, `oauth_subject: str`, `email: str`, `name: str`, `avatar_url: str | None`, `created_at: datetime`. Unique constraint on `(oauth_provider, oauth_subject)`.
  - `app.repos.users.upsert_user(db, *, provider, subject, email, name, avatar_url) -> User` and `get_user(db, user_id) -> User | None`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_users_repo.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app.repos.users import upsert_user, get_user

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()

async def test_upsert_creates_then_updates(db):
    u1 = await upsert_user(db, provider="google", subject="abc",
                           email="a@x.com", name="A", avatar_url=None)
    assert u1.id is not None
    u2 = await upsert_user(db, provider="google", subject="abc",
                           email="a@x.com", name="A Renamed", avatar_url="http://img")
    assert u2.id == u1.id          # same identity, not a duplicate
    assert u2.name == "A Renamed"
    fetched = await get_user(db, u1.id)
    assert fetched is not None and fetched.email == "a@x.com"
```

Add the sqlite async driver for tests: `cd api && uv add --dev aiosqlite`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_users_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/app/db.py`:
```python
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

class Base(DeclarativeBase):
    pass

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
```

Create `api/app/models.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("oauth_provider", "oauth_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    oauth_provider: Mapped[str] = mapped_column(String(32))
    oauth_subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Create `api/app/repos/__init__.py` (empty file).

Create `api/app/repos/users.py`:
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User

async def upsert_user(db: AsyncSession, *, provider: str, subject: str,
                      email: str, name: str, avatar_url: str | None) -> User:
    stmt = select(User).where(
        User.oauth_provider == provider, User.oauth_subject == subject
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(oauth_provider=provider, oauth_subject=subject,
                    email=email, name=name, avatar_url=avatar_url)
        db.add(user)
    else:
        user.email, user.name, user.avatar_url = email, name, avatar_url
    await db.commit()
    await db.refresh(user)
    return user

async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_users_repo.py -v`
Expected: PASS (both upsert branches and fetch).

- [ ] **Step 5: Create the Alembic migration for production Postgres**

Run: `cd api && uv run alembic init -t async migrations` then replace `api/alembic.ini` `sqlalchemy.url` line with `sqlalchemy.url =` (left blank; set in env.py) and set `api/migrations/env.py` to use our settings + Base:
```python
# migrations/env.py — key edits
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.config import get_settings
from app.db import Base
import app.models  # noqa: F401  ensure models are imported

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=get_settings().database_url,
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run(conn):
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(do_run)
    await engine.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```
Then generate the migration: `cd api && uv run alembic revision --autogenerate -m "users"` and confirm it creates `migrations/versions/0001_users.py` with the `users` table. Rename the file prefix to `0001_users.py` if needed.

- [ ] **Step 6: Commit**

```bash
git add api/
git commit -m "feat: user model, repo, and initial migration"
```

---

## Task 3: Session helpers + auth dependency

**Files:**
- Create: `api/app/session.py`
- Test: `api/tests/test_session.py`

**Interfaces:**
- Consumes: `app.repos.users.get_user`, `app.db.get_db`.
- Produces:
  - `app.session.login_session(request, user_id: int) -> None` — stores `user_id` in the Starlette session.
  - `app.session.logout_session(request) -> None`.
  - `app.session.current_user(request, db) -> User` — FastAPI dependency; raises `HTTPException(401)` when there is no session user or the user is missing.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_session.py`:
```python
import pytest
from starlette.requests import Request
from app.session import login_session, logout_session

def make_request():
    scope = {"type": "http", "session": {}}
    return Request(scope)

def test_login_and_logout_mutate_session():
    req = make_request()
    login_session(req, 42)
    assert req.session["user_id"] == 42
    logout_session(req)
    assert "user_id" not in req.session
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.session'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/app/session.py`:
```python
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.repos.users import get_user
from app.models import User

def login_session(request: Request, user_id: int) -> None:
    request.session["user_id"] = user_id

def logout_session(request: Request) -> None:
    request.session.pop("user_id", None)

async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/
git commit -m "feat: session login/logout helpers and current_user dependency"
```

---

## Task 4: `/api/me` and logout routes (protected)

**Files:**
- Create: `api/app/routes/me.py`
- Modify: `api/app/main.py` (add SessionMiddleware + include `me` router)
- Test: `api/tests/test_me.py`

**Interfaces:**
- Consumes: `app.session.current_user`, `app.session.logout_session`.
- Produces: `GET /api/me` → `{"id","email","name","avatar_url"}` for the logged-in user, else 401. `POST /api/auth/logout` → `{"ok": true}` and clears the session.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_me.py`:
```python
from app.models import User
from app.session import current_user

async def test_me_requires_auth(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401

async def test_me_returns_user_when_authenticated(app, client):
    fake = User(id=7, oauth_provider="google", oauth_subject="s",
                email="z@x.com", name="Zed", avatar_url=None)
    app.dependency_overrides[current_user] = lambda: fake
    resp = await client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "z@x.com"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_me.py -v`
Expected: FAIL — `/api/me` returns 404 (route not defined yet).

- [ ] **Step 3: Write minimal implementation**

Create `api/app/routes/me.py`:
```python
from fastapi import APIRouter, Depends, Request
from app.session import current_user, logout_session
from app.models import User

router = APIRouter()

@router.get("/api/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email,
            "name": user.name, "avatar_url": user.avatar_url}

@router.post("/api/auth/logout")
async def logout(request: Request):
    logout_session(request)
    return {"ok": True}
```

Modify `api/app/main.py` to add session middleware and the router:
```python
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.routes import health, me

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="YDG DocMind API")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       same_site="lax", https_only=False)
    app.include_router(health.router)
    app.include_router(me.router)
    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_me.py -v`
Expected: PASS (both 401 and authenticated cases).

- [ ] **Step 5: Commit**

```bash
git add api/
git commit -m "feat: /api/me and logout routes behind session auth"
```

---

## Task 5: OAuth login + callback (Google, GitHub, Twitter)

**Files:**
- Create: `api/app/auth.py`
- Modify: `api/app/config.py` (add OAuth client envs), `api/app/main.py` (include auth router)
- Test: `api/tests/test_auth_flow.py`

**Interfaces:**
- Consumes: `app.repos.users.upsert_user`, `app.session.login_session`, `app.db.get_db`.
- Produces:
  - `GET /api/auth/{provider}/login` → 302 redirect to the provider (provider ∈ `google|github|twitter`); unknown provider → 404.
  - `GET /api/auth/{provider}/callback` → upserts the user, sets session, 302-redirects to `settings.frontend_url`.
  - `app.auth.normalize_userinfo(provider, raw: dict) -> dict` with keys `subject, email, name, avatar_url` — pure function, unit-tested.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_auth_flow.py`:
```python
import pytest
from app.auth import normalize_userinfo

def test_normalize_google():
    raw = {"sub": "g1", "email": "g@x.com", "name": "G User", "picture": "http://p"}
    out = normalize_userinfo("google", raw)
    assert out == {"subject": "g1", "email": "g@x.com",
                   "name": "G User", "avatar_url": "http://p"}

def test_normalize_github():
    raw = {"id": 555, "email": "h@x.com", "name": "H", "avatar_url": "http://a"}
    out = normalize_userinfo("github", raw)
    assert out["subject"] == "555" and out["avatar_url"] == "http://a"

def test_normalize_unknown_raises():
    with pytest.raises(ValueError):
        normalize_userinfo("myspace", {})

async def test_login_unknown_provider_404(client):
    resp = await client.get("/api/auth/myspace/login")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_auth_flow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`.

- [ ] **Step 3: Add OAuth settings**

Modify `api/app/config.py` — add these fields to `Settings`:
```python
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    api_base_url: str = "http://localhost:8000"
```

- [ ] **Step 4: Write minimal implementation**

Create `api/app/auth.py`:
```python
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.db import get_db
from app.repos.users import upsert_user
from app.session import login_session

router = APIRouter()
settings = get_settings()
oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
oauth.register(
    name="github",
    client_id=settings.github_client_id,
    client_secret=settings.github_client_secret,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)
oauth.register(
    name="twitter",
    client_id=settings.twitter_client_id,
    client_secret=settings.twitter_client_secret,
    access_token_url="https://api.twitter.com/2/oauth2/token",
    authorize_url="https://twitter.com/i/oauth2/authorize",
    api_base_url="https://api.twitter.com/2/",
    client_kwargs={"scope": "tweet.read users.read", "code_challenge_method": "S256"},
)

PROVIDERS = {"google", "github", "twitter"}

def normalize_userinfo(provider: str, raw: dict) -> dict:
    if provider == "google":
        return {"subject": raw["sub"], "email": raw.get("email", ""),
                "name": raw.get("name", ""), "avatar_url": raw.get("picture")}
    if provider == "github":
        return {"subject": str(raw["id"]), "email": raw.get("email") or "",
                "name": raw.get("name") or raw.get("login", ""),
                "avatar_url": raw.get("avatar_url")}
    if provider == "twitter":
        d = raw.get("data", raw)
        return {"subject": str(d["id"]), "email": d.get("email", ""),
                "name": d.get("name", d.get("username", "")),
                "avatar_url": d.get("profile_image_url")}
    raise ValueError(f"unknown provider: {provider}")

def _client(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown provider")
    return getattr(oauth, provider)

@router.get("/api/auth/{provider}/login")
async def login(provider: str, request: Request):
    client = _client(provider)
    redirect_uri = f"{settings.api_base_url}/api/auth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)

@router.get("/api/auth/{provider}/callback")
async def callback(provider: str, request: Request,
                   db: AsyncSession = Depends(get_db)):
    client = _client(provider)
    token = await client.authorize_access_token(request)
    if provider == "google":
        raw = token.get("userinfo") or await client.userinfo(token=token)
    elif provider == "github":
        raw = (await client.get("user", token=token)).json()
    else:  # twitter
        raw = (await client.get("users/me?user.fields=profile_image_url",
                                token=token)).json()
    info = normalize_userinfo(provider, dict(raw))
    user = await upsert_user(db, provider=provider, subject=info["subject"],
                             email=info["email"], name=info["name"],
                             avatar_url=info["avatar_url"])
    login_session(request, user.id)
    return RedirectResponse(url=settings.frontend_url)
```

Modify `api/app/main.py` `create_app()` to include the auth router:
```python
from app.routes import health, me
from app import auth as auth_routes
# ... inside create_app(), after other routers:
    app.include_router(auth_routes.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_auth_flow.py -v`
Expected: PASS (3 normalize unit tests + unknown-provider 404).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd api && uv run pytest -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add api/
git commit -m "feat: OAuth login and callback for google/github/twitter"
```

---

## Task 6: Containerize the API + compose stack (postgres, redis, milvus)

**Files:**
- Create: `api/Dockerfile`, `docker-compose.yml`, `.env.example`
- Modify: `.gitignore` (ensure `.env` ignored)

**Interfaces:**
- Consumes: the FastAPI app (`app.main:app`), Alembic migrations.
- Produces: a running stack — `api` on `:8000`, `postgres` on `:5432`, `redis` on `:6379`, `milvus` on `:19530`. (`web` service is added in Task 9.)

- [ ] **Step 1: Write the API Dockerfile**

Create `api/Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `.env.example`**

Create `.env.example`:
```
# Backend
DATABASE_URL=postgresql+asyncpg://docmind:docmind@postgres:5432/docmind
SESSION_SECRET=change-me-to-a-long-random-string
FRONTEND_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000
REDIS_URL=redis://redis:6379/0
MILVUS_URI=http://milvus:19530

# NVIDIA NeMo Retriever (used from Phase 2 onward)
NVIDIA_API_KEY=
NIM_EMBED_URL=https://integrate.api.nvidia.com/v1
NIM_RERANK_URL=https://integrate.api.nvidia.com/v1
NIM_PAGE_ELEMENTS_URL=
NIM_TABLE_STRUCTURE_URL=
NIM_CHART_URL=
NIM_OCR_URL=

# Generation providers (Phase 3+)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# OAuth apps
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
TWITTER_CLIENT_ID=
TWITTER_CLIENT_SECRET=
```

- [ ] **Step 3: Write `docker-compose.yml`**

Create `docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: docmind
      POSTGRES_PASSWORD: docmind
      POSTGRES_DB: docmind
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U docmind"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7
    ports: ["6379:6379"]

  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd

  minio:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data
    volumes: ["minio:/minio_data"]

  milvus:
    image: milvusdb/milvus:v2.4.4
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    ports: ["19530:19530"]
    depends_on: [etcd, minio]

  api:
    build: ./api
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://docmind:docmind@postgres:5432/docmind
    ports: ["8000:8000"]
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pgdata:
  minio:
```

- [ ] **Step 4: Bring up infra and run migrations**

Run:
```bash
cp .env.example .env   # then edit SESSION_SECRET
docker compose up -d postgres redis etcd minio milvus
cd api && DATABASE_URL=postgresql+asyncpg://docmind:docmind@localhost:5432/docmind uv run alembic upgrade head
```
Expected: Alembic prints `Running upgrade -> 0001, users`. Verify table: `docker compose exec postgres psql -U docmind -c "\dt"` lists `users` and `alembic_version`.

- [ ] **Step 5: Bring up the API and verify health**

Run:
```bash
docker compose up -d --build api
curl -s http://localhost:8000/api/health
```
Expected: `{"status":"ok"}`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml api/Dockerfile .env.example .gitignore
git commit -m "chore: dockerize api and add full compose stack"
```

---

## Task 7: Frontend scaffold — login screen + auth gate

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tailwind.config.js`, `web/postcss.config.js`, `web/index.html`, `web/src/main.tsx`, `web/src/index.css`, `web/src/api.ts`, `web/src/auth.tsx`, `web/src/App.tsx`, `web/src/components/LoginScreen.tsx`, `web/src/components/AppShell.tsx`
- Test: `web/src/components/__tests__/LoginScreen.test.tsx`

**Interfaces:**
- Consumes: `GET /api/me`, `GET /api/auth/{provider}/login`, `POST /api/auth/logout`.
- Produces: a React app that shows `LoginScreen` when `/api/me` is 401 and `AppShell` (empty KB shell + avatar + logout) when authenticated.

- [ ] **Step 1: Scaffold the Vite app and add deps**

Run:
```bash
npm create vite@latest web -- --template react-ts
cd web
npm install
npm install @tanstack/react-query
npm install -D tailwindcss postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom jsdom
npx tailwindcss init -p
```

- [ ] **Step 2: Configure Tailwind, Vite proxy, and Vitest**

Set `web/tailwind.config.js` `content`:
```js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```
Replace `web/src/index.css` with:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```
Set `web/vite.config.ts`:
```ts
/// <reference types="vitest" />
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts" },
})
```
Create `web/src/setupTests.ts`:
```ts
import "@testing-library/jest-dom"
```

- [ ] **Step 3: Write the failing component test**

Create `web/src/components/__tests__/LoginScreen.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { LoginScreen } from "../LoginScreen"

describe("LoginScreen", () => {
  it("shows the product name and three OAuth buttons", () => {
    render(<LoginScreen />)
    expect(screen.getByText(/YDG DocMind/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Google/i }))
      .toHaveAttribute("href", "/api/auth/google/login")
    expect(screen.getByRole("link", { name: /GitHub/i }))
      .toHaveAttribute("href", "/api/auth/github/login")
    expect(screen.getByRole("link", { name: /Twitter/i }))
      .toHaveAttribute("href", "/api/auth/twitter/login")
  })
})
```
Add to `web/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 4: Run test to verify it fails**

Run: `cd web && npm test`
Expected: FAIL — cannot resolve `../LoginScreen`.

- [ ] **Step 5: Write minimal implementation**

Create `web/src/components/LoginScreen.tsx`:
```tsx
const PROVIDERS = [
  { id: "google", label: "Continue with Google" },
  { id: "github", label: "Continue with GitHub" },
  { id: "twitter", label: "Continue with Twitter" },
]

export function LoginScreen() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-slate-50">
      <h1 className="text-3xl font-semibold">YDG DocMind</h1>
      <p className="text-slate-500">Chat with any document. Tables, charts and all.</p>
      <div className="flex flex-col gap-3 w-72">
        {PROVIDERS.map((p) => (
          <a key={p.id} href={`/api/auth/${p.id}/login`}
             className="rounded-lg border px-4 py-2 text-center hover:bg-slate-100">
            {p.label}
          </a>
        ))}
      </div>
    </div>
  )
}
```

Create `web/src/components/AppShell.tsx`:
```tsx
type User = { name: string; avatar_url: string | null }

export function AppShell({ user }: { user: User }) {
  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="font-semibold">YDG DocMind</span>
        <div className="flex items-center gap-3">
          {user.avatar_url && (
            <img src={user.avatar_url} alt="" className="h-8 w-8 rounded-full" />
          )}
          <span>{user.name}</span>
          <button
            onClick={async () => {
              await fetch("/api/auth/logout", { method: "POST" })
              window.location.reload()
            }}
            className="text-sm text-slate-500 hover:underline">
            Sign out
          </button>
        </div>
      </header>
      <main className="p-8">
        <div className="rounded-xl border border-dashed p-12 text-center text-slate-400">
          No knowledge bases yet. (Creation arrives in Phase 2.)
        </div>
      </main>
    </div>
  )
}
```

Create `web/src/api.ts`:
```ts
export type Me = { id: number; email: string; name: string; avatar_url: string | null }

export async function fetchMe(): Promise<Me | null> {
  const res = await fetch("/api/me")
  if (res.status === 401) return null
  if (!res.ok) throw new Error("failed to load session")
  return res.json()
}
```

Create `web/src/auth.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query"
import { fetchMe } from "./api"

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false })
}
```

Create `web/src/App.tsx`:
```tsx
import { useMe } from "./auth"
import { LoginScreen } from "./components/LoginScreen"
import { AppShell } from "./components/AppShell"

export default function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return <div className="p-8 text-slate-400">Loading…</div>
  if (!me) return <LoginScreen />
  return <AppShell user={me} />
}
```

Replace `web/src/main.tsx`:
```tsx
import React from "react"
import ReactDOM from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import App from "./App"
import "./index.css"

const qc = new QueryClient()
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}><App /></QueryClientProvider>
  </React.StrictMode>,
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd web && npm test`
Expected: PASS — login screen renders name + three provider links.

- [ ] **Step 7: Commit**

```bash
git add web/
git commit -m "feat: react login screen and authenticated app shell"
```

---

## Task 8: Frontend container + end-to-end stack verification + README

**Files:**
- Create: `web/Dockerfile`, `web/nginx.conf`, `README.md`
- Modify: `docker-compose.yml` (add `web` service)

**Interfaces:**
- Consumes: the built React app, the `api` service.
- Produces: `web` served on `:5173`, proxying `/api` to `api:8000`; a documented one-command run.

- [ ] **Step 1: Write the web Dockerfile and nginx proxy**

Create `web/Dockerfile`:
```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```
Create `web/nginx.conf`:
```nginx
server {
  listen 80;
  location /api/ { proxy_pass http://api:8000; proxy_set_header Host $host; }
  location / { root /usr/share/nginx/html; try_files $uri /index.html; }
}
```

- [ ] **Step 2: Add the `web` service to compose**

Add to `docker-compose.yml` under `services:`:
```yaml
  web:
    build: ./web
    ports: ["5173:80"]
    depends_on: [api]
```

- [ ] **Step 3: Write the README**

Create `README.md`:
```markdown
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
```

- [ ] **Step 4: Full-stack verification**

Run:
```bash
docker compose up -d --build
curl -s http://localhost:8000/api/health      # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/me   # 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173          # 200
```
Expected: health ok, `/api/me` returns `401` unauthenticated, web root returns `200`.

- [ ] **Step 5: Manual OAuth smoke test (requires real Google credentials in `.env`)**

Open `http://localhost:5173`, click **Continue with Google**, complete consent, and confirm you land back on the authenticated shell showing your name/avatar and a **Sign out** button. Click **Sign out** and confirm you return to the login screen.

- [ ] **Step 6: Commit**

```bash
git add web/Dockerfile web/nginx.conf README.md docker-compose.yml
git commit -m "chore: containerize web, wire full compose stack, add README"
```

---

## Phase 1 Done — Definition of Done

- `docker compose up -d --build` brings up postgres, redis, milvus (+etcd/minio), api, web.
- Unauthenticated users see only the login screen; `/api/me` is 401.
- Signing in with Google/GitHub/Twitter creates/updates a `users` row and lands on the authenticated shell; sign-out returns to login.
- `cd api && uv run pytest` and `cd web && npm test` both pass.

## Next phases (separate plans, generated when we reach them)

- **Phase 2 — Ingestion core:** upload → nv-ingest (text-only) → embed (NIM) → Milvus → `ready`, with arq worker + live status.
- **Phase 3 — Chat core:** hybrid search → rerank (NIM) → `LLMRouter` generation → SSE streaming. *(MVP demoable.)*
- **Phase 4 — Multimodal:** tables + charts extraction as first-class chunks.
- **Phase 5 — Rich citations:** source panel with rendered tables/charts + page links.
- **Phase 6 — Polish:** KB management, progress bars, model switcher, graceful degradation.
