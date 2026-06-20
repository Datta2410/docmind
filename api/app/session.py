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
