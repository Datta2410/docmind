from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://docmind:docmind@localhost:5432/docmind"
    session_secret: str = "dev-insecure-change-me"
    frontend_url: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    api_base_url: str = "http://localhost:8000"


def get_settings() -> Settings:
    return Settings()
