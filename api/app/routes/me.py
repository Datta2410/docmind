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
