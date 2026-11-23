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

    # Attachments: how much of each notice's attached files the judge reads.
    max_attachments: int = Field(default=5, ge=0)
    max_attachment_bytes: int = Field(default=15_000_000, ge=1)
    attachment_char_limit: int = Field(default=60_000, ge=1000)

    # Accounts and hosting.
    app_base_url: str = "http://127.0.0.1:8000"
    cookie_secure: bool = False
    session_days: int = Field(default=14, ge=1)
    allow_signup: bool = True

    # Daily job and email digest.
    daily_run_hour_utc: int = Field(default=11, ge=0, le=23)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    # Gets an email when a daily run fails or a company's digest errors.
    admin_email: str | None = None
    # Hours after which /health/ready reports the daily data as stale.
    stale_after_hours: int = Field(default=30, ge=1)

    # Brute-force protection for sign-in.
    login_max_failures: int = Field(default=8, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
