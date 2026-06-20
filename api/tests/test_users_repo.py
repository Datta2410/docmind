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
