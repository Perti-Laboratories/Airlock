from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

DOMAIN_ID = "ffbfcc90-9e93-4cb8-9943-890f4b293201"
USER_ID = "bc476519-2471-44f5-9a8d-8010a49b87ce"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIRLOCK_", env_file=".env", extra="ignore")
    database_url: str
    session_secret: str = Field(min_length=32)
    port: int = Field(default=8741, ge=1024, le=65535)
    model: str = "qwen3:8b"
    embedding_model: str = "nomic-embed-text:latest"
    ollama_url: str = "http://127.0.0.1:11435"
    model_timeout: float = Field(default=180, ge=1, le=600)
    workspace_timezone: str = "America/New_York"
    workers_enabled: bool = True
    exchange_allow_loopback: bool = False
    workspace_name: str = "Personal test workspace"

    @field_validator("database_url")
    @classmethod
    def isolated_database(cls, value):
        u = make_url(value)
        if u.drivername != "postgresql+psycopg" or u.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Airlock requires a local Postgres connection.")
        if not u.database or not u.database.startswith("airlock") or u.username != "airlock":
            raise ValueError("Use a dedicated airlock database and role, never connected planner's database.")
        return value

    @field_validator("ollama_url")
    @classmethod
    def local_ollama(cls, value):
        u = urlsplit(value)
        if (u.scheme != "http" or u.hostname not in {"127.0.0.1", "::1"}
                or u.username or u.password or u.query or u.fragment or u.path not in {"", "/"}):
            raise ValueError("Ollama must be a literal loopback HTTP endpoint.")
        return value.rstrip("/")

    @field_validator("model", "embedding_model")
    @classmethod
    def local_model_name(cls, value):
        if not value.strip() or "cloud" in value.lower() or "/" in value or len(value) > 120:
            raise ValueError("Choose an installed local Ollama model.")
        return value

    @field_validator("workspace_timezone")
    @classmethod
    def valid_zone(cls, value):
        from zoneinfo import ZoneInfo
        ZoneInfo(value)
        return value

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"
