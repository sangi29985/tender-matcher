from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    sam_gov_api_key: str | None = None
    anthropic_api_key: str | None = None
    database_url: str = "sqlite:///./tender_matcher.db"
    ollama_host: str = "http://localhost:11434"
    anthropic_model: str = "claude-sonnet-5-5"
    top_k: int = Field(default=30, ge=1)
    judge_concurrency: int = Field(default=4, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
