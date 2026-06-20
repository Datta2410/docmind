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
