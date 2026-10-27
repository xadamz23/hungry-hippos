from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hh:hh@127.0.0.1:5433/hungry_hippos"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    tz: str = "America/Detroit"


@lru_cache
def get_settings() -> Settings:
    return Settings()
