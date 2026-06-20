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
