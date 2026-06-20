from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent request inserted the same (provider, subject) first.
            await db.rollback()
            user = (await db.execute(stmt)).scalar_one()
            user.email, user.name, user.avatar_url = email, name, avatar_url
            await db.commit()
            await db.refresh(user)
            return user
        await db.refresh(user)
        return user
    user.email, user.name, user.avatar_url = email, name, avatar_url
    await db.commit()
    await db.refresh(user)
    return user


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)
