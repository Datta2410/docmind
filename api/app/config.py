from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://docmind:docmind@localhost:5432/docmind"
    session_secret: str = "dev-insecure-change-me"
    frontend_url: str = "http://localhost:5173"


def get_settings() -> Settings:
    return Settings()
